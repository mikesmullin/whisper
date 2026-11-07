"""
Shared helpers for the whisper / perception-voice integration tests.

Speaks the perception-voice IPC protocol directly (4-byte big-endian
length prefix + JSON payload) so the tests can run from any venv without
importing the perception_voice package.
"""

from __future__ import annotations

import json
import os
import re
import socket
import struct
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# --- layout -----------------------------------------------------------------

WHISPER_DIR = Path(__file__).resolve().parent.parent
PERCEPTION_DIR = Path("/workspace/perception-voice")
SOCKET_PATH = PERCEPTION_DIR / "perception.sock"
PERCEPTION_BIN = PERCEPTION_DIR / ".venv" / "bin" / "perception-voice"

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_WAV = FIXTURE_DIR / "speech.wav"
FIXTURE_INJECT_WAV = FIXTURE_DIR / "speech_inject.wav"
FIXTURE_TXT = FIXTURE_DIR / "speech.txt"

UNITS = ("perception-voice", "whisper")

# --- IPC --------------------------------------------------------------------

HEADER = struct.Struct(">I")

# streams.py: 36 bytes little-endian - magic, stream_id, rms, band[4], pitch, flags
LEVEL_FRAME = struct.Struct("<II6fI")
LEVEL_MAGIC = 0x31465641  # 'AVF1'


def _connect(timeout: float = 2.0) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(str(SOCKET_PATH))
    return sock


def _send(sock: socket.socket, msg: dict) -> None:
    payload = json.dumps(msg).encode()
    sock.sendall(HEADER.pack(len(payload)) + payload)


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv(sock: socket.socket) -> Optional[dict]:
    head = _recv_exact(sock, HEADER.size)
    if not head:
        return None
    body = _recv_exact(sock, HEADER.unpack(head)[0])
    if not body:
        return None
    return json.loads(body.decode())


def request(msg: dict, timeout: float = 2.0) -> Optional[dict]:
    """Send one request/response pair. Returns None if unreachable."""
    if not SOCKET_PATH.exists():
        return None
    try:
        sock = _connect(timeout)
    except OSError:
        return None
    try:
        _send(sock, msg)
        return _recv(sock)
    except OSError:
        return None
    finally:
        sock.close()


def set_marker(uid: str) -> bool:
    r = request({"command": "set", "uid": uid})
    return bool(r and r.get("status") == "ok")


def get_transcriptions(uid: str) -> list[dict]:
    """Utterances since this uid's read marker."""
    r = request({"command": "get", "uid": uid})
    if not r or r.get("status") != "ok":
        return []
    out = []
    for line in (r.get("text") or "").strip().split("\n"):
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def wait_for_audio_frames(timeout: float, min_frames: int = 2) -> Optional[float]:
    """Block until the server pushes real audio feature frames.

    The `levels` channel emits unconditionally (not VAD-gated) at ~125
    frames/s for every captured mic chunk, so the first frame is proof
    that PortAudio's audio callback is actually firing -- i.e. capture
    is live, not just that the process is up.

    Returns seconds waited, or None on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not SOCKET_PATH.exists():
            time.sleep(0.01)
            continue
        try:
            sock = _connect(timeout=0.5)
        except OSError:
            time.sleep(0.01)
            continue
        try:
            t0 = time.monotonic()
            _send(sock, {"command": "subscribe", "channel": "levels"})
            ack = _recv(sock)
            if not ack or ack.get("status") != "ok":
                continue
            sock.settimeout(max(0.05, deadline - time.monotonic()))
            buf, seen = b"", 0
            while time.monotonic() < deadline:
                data = sock.recv(4096)
                if not data:
                    break
                buf += data
                while len(buf) >= LEVEL_FRAME.size:
                    frame, buf = buf[:LEVEL_FRAME.size], buf[LEVEL_FRAME.size:]
                    if LEVEL_FRAME.unpack(frame)[0] != LEVEL_MAGIC:
                        buf = b""  # desync; resync on next read
                        break
                    seen += 1
                    if seen >= min_frames:
                        return time.monotonic() - t0
        except (OSError, struct.error):
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
        time.sleep(0.01)
    return None


def measure_level(duration: float = 1.0) -> Optional[float]:
    """Mean compressed RMS over `duration` of live capture (0.0-1.0)."""
    if not SOCKET_PATH.exists():
        return None
    try:
        sock = _connect(timeout=1.0)
    except OSError:
        return None
    try:
        _send(sock, {"command": "subscribe", "channel": "levels"})
        if not (_recv(sock) or {}).get("status") == "ok":
            return None
        deadline = time.monotonic() + duration
        sock.settimeout(duration + 0.5)
        buf, total, n = b"", 0.0, 0
        while time.monotonic() < deadline:
            data = sock.recv(4096)
            if not data:
                break
            buf += data
            while len(buf) >= LEVEL_FRAME.size:
                frame, buf = buf[:LEVEL_FRAME.size], buf[LEVEL_FRAME.size:]
                fields = LEVEL_FRAME.unpack(frame)
                if fields[0] != LEVEL_MAGIC:
                    buf = b""
                    break
                total += fields[2]
                n += 1
        return (total / n) if n else None
    except (OSError, struct.error):
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


# --- systemd ----------------------------------------------------------------

def systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True, check=check,
    )


def restart_units(units: Iterable[str] = UNITS) -> float:
    """Restart the services. Returns the monotonic clock at issue time.

    `systemctl restart` blocks until the units are activated, but these
    are Type=simple, so activation means "process spawned" -- readiness
    is measured separately against the IPC socket.
    """
    units = list(units)
    # Removing the socket first makes "socket exists" an unambiguous
    # readiness edge rather than a leftover from the previous process.
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass
    t0 = time.monotonic()
    systemctl("restart", *units)
    return t0


def unit_active(unit: str) -> bool:
    return systemctl("is-active", unit, check=False).stdout.strip() == "active"


# --- audio ------------------------------------------------------------------

def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def wav_peak_dbfs(path: Path) -> float:
    """Peak level of a 16-bit mono/stereo wav, in dBFS."""
    import array
    import math
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit PCM")
        frames = w.readframes(w.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    peak = max((abs(s) for s in samples), default=0)
    return -96.0 if peak == 0 else 20.0 * math.log10(peak / 32768.0)


# --- fixture preparation ----------------------------------------------------

#: Target RMS for injected audio. A quiet take (the Zone 301's HFP mic
#: records speech around -53 dBFS RMS) is below what WebRTC VAD mode 3
#: will pass, so the raw recording is normalized to a level representative
#: of normal dictation before injection.
INJECT_TARGET_RMS_DBFS = -26.0

#: Silence padded onto each end. The leading pad lets the virtual mic and
#: VAD settle before speech starts (without it the first words are lost);
#: the trailing pad exceeds post_speech_silence_duration so the VAD closes
#: the utterance on its own.
INJECT_LEAD_SILENCE_S = 1.0
INJECT_TAIL_SILENCE_S = 1.5


def wav_rms_dbfs(path: Path) -> float:
    """RMS level of a 16-bit wav, in dBFS."""
    import array
    import math
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit PCM")
        frames = w.readframes(w.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    if not samples:
        return -96.0
    mean_sq = sum(float(s) * s for s in samples) / len(samples)
    rms = math.sqrt(mean_sq) / 32768.0
    return -96.0 if rms <= 0 else 20.0 * math.log10(rms)


def prepare_injection_wav(
    src: Path = None,
    dst: Path = None,
    target_rms_dbfs: float = INJECT_TARGET_RMS_DBFS,
) -> Path:
    """Derive the injected wav from the raw recording.

    Normalizes to `target_rms_dbfs` and pads silence on both ends.
    Regenerated whenever the source recording is newer than the result,
    so re-recording the fixture is enough to refresh it.
    """
    src = src or FIXTURE_WAV
    dst = dst or FIXTURE_INJECT_WAV
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst

    gain_db = target_rms_dbfs - wav_rms_dbfs(src)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-t", str(INJECT_LEAD_SILENCE_S),
            "-i", "anullsrc=r=16000:cl=mono",
            "-i", str(src),
            "-f", "lavfi", "-t", str(INJECT_TAIL_SILENCE_S),
            "-i", "anullsrc=r=16000:cl=mono",
            "-filter_complex",
            f"[1:a]volume={gain_db:.2f}dB[v];[0:a][v][2:a]concat=n=3:v=0:a=1[out]",
            "-map", "[out]", "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le", str(dst), "-y",
        ],
        check=True, capture_output=True,
    )
    return dst


# --- text comparison --------------------------------------------------------

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def word_overlap(expected: str, actual: str) -> float:
    """Fraction of expected words present in actual (bag-of-words recall)."""
    exp = normalize(expected).split()
    act = list(normalize(actual).split())
    if not exp:
        return 0.0
    hit = 0
    for word in exp:
        if word in act:
            act.remove(word)
            hit += 1
    return hit / len(exp)


@dataclass
class Iteration:
    n: int
    ready_s: Optional[float]
    transcribe_s: Optional[float]
    text: str
    overlap: float
    ok: bool
    note: str = ""
