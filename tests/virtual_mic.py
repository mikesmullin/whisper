"""
A PipeWire virtual microphone, so a fixed wav can be injected into the
*real* capture path.

pw-loopback publishes a sink/source pair; making the source the system
default source means ALSA's `default` device -- which is exactly what
perception-voice opens through PortAudio -- reads whatever is played
into the sink. Nothing in either service needs to know it is a test.

    pw-play --target <sink>  ->  loopback  ->  <source>  ->  ALSA default
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

SINK = "wtest_sink"
SOURCE = "wtest_mic"


def _pactl(*args: str, check: bool = True) -> str:
    return subprocess.run(["pactl", *args], capture_output=True, text=True,
                          check=check).stdout.strip()


def default_source() -> str:
    return _pactl("get-default-source")


def _source_exists(name: str) -> bool:
    return any(line.split("\t")[1:2] == [name]
               for line in _pactl("list", "short", "sources").split("\n") if line)


class VirtualMic:
    """Context manager: publish the virtual mic and make it the default."""

    def __init__(self, log_path: Path | None = None) -> None:
        self._proc: subprocess.Popen | None = None
        self._saved_default: str | None = None
        self._log_path = log_path

    def __enter__(self) -> "VirtualMic":
        self._saved_default = default_source()
        log = open(self._log_path, "wb") if self._log_path else subprocess.DEVNULL
        self._proc = subprocess.Popen(
            [
                "pw-loopback",
                "--capture-props="
                f"media.class=Audio/Sink node.name={SINK} "
                f"node.description=whisper-test-sink audio.position=[MONO]",
                "--playback-props="
                f"media.class=Audio/Source node.name={SOURCE} "
                f"node.description=whisper-test-mic audio.position=[MONO]",
            ],
            stdout=log, stderr=subprocess.STDOUT,
        )

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if _source_exists(SOURCE):
                break
            if self._proc.poll() is not None:
                raise RuntimeError("pw-loopback exited before publishing a source")
            time.sleep(0.1)
        else:
            raise RuntimeError(f"virtual source {SOURCE!r} never appeared")

        _pactl("set-default-source", SOURCE)
        time.sleep(0.5)  # let WirePlumber settle before anything opens it
        return self

    def __exit__(self, *_exc) -> None:
        if self._saved_default:
            _pactl("set-default-source", self._saved_default, check=False)
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def play(self, wav: Path, wait: bool = True) -> None:
        """Play a wav into the virtual mic (blocking by default)."""
        proc = subprocess.Popen(
            ["pw-play", "--target", SINK, str(wav)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if wait:
            proc.wait()
