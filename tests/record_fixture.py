#!/usr/bin/env python3
"""
Record a speech fixture from the real default microphone.

The resulting wav becomes the fixed input for the integration test, so
every later run exercises the pipeline with identical audio.

    tests/record_fixture.py --seconds 6 --text "the quick brown fox ..."

Writes tests/fixtures/speech.wav (16 kHz mono 16-bit) and speech.txt
(the expected transcript, used for the match assertion).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURE_TXT, FIXTURE_WAV, wav_duration, wav_peak_dbfs  # noqa: E402

#: Below this peak the recording is silence / noise floor, not speech.
MIN_PEAK_DBFS = -40.0

#: pw-record needs time to negotiate and start the capture stream. Prompt
#: the speaker only *after* this has elapsed, or the first word is spoken
#: into a stream that is not recording yet and is simply missing from the
#: file -- which looks exactly like the model mis-hearing the opening words.
STREAM_SETTLE_S = 1.0


def default_source() -> str:
    return subprocess.run(
        ["pactl", "get-default-source"], capture_output=True, text=True
    ).stdout.strip()


def record(path: Path, seconds: float, source: str | None) -> None:
    """Start capture, let the stream settle, then prompt and record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16"]
    if source:
        cmd += ["--target", source]
    cmd.append(str(path))

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        # Stream is opening here -- do not prompt yet.
        print("  opening capture stream... ", end="", flush=True)
        time.sleep(STREAM_SETTLE_S)
        if proc.poll() is not None:
            raise RuntimeError("pw-record exited before capture started")
        print("live")
        print()
        print("  >>> SPEAK NOW <<<")
        for remaining in range(int(seconds), 0, -1):
            print(f"\r      {remaining:2d}s left ", end="", flush=True)
            time.sleep(1)
        time.sleep(seconds - int(seconds))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("\r      done        ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=6.0,
                    help="recording length (default: 6)")
    ap.add_argument("--text", default=None,
                    help="the transcript you are about to speak "
                         "(stored as the expected result)")
    ap.add_argument("--source", default=None,
                    help="PipeWire source name (default: system default)")
    ap.add_argument("--out", type=Path, default=FIXTURE_WAV)
    args = ap.parse_args()

    source = args.source or default_source()
    print(f"Microphone: {source}")
    print()
    if args.text:
        print("Say this, clearly, at your normal dictation volume:")
        print(f'\n    "{args.text}"\n')
    else:
        print("Speak a sentence or two at your normal dictation volume.")
    print(f"Capture opens first, then you will be prompted to speak "
          f"for {args.seconds:g}s.")
    print("Wait for SPEAK NOW -- speaking before it loses your first words.")
    print()

    record(args.out, args.seconds, args.source)

    peak = wav_peak_dbfs(args.out)
    dur = wav_duration(args.out)
    print()
    print(f"  file:     {args.out}")
    print(f"  duration: {dur:.2f}s")
    print(f"  peak:     {peak:.1f} dBFS")

    if peak < MIN_PEAK_DBFS:
        print()
        print(f"  FAIL: peak {peak:.1f} dBFS is below {MIN_PEAK_DBFS:g} dBFS -- "
              "that is the noise floor, not speech.")
        print("  The microphone captured nothing. Check that the headset is")
        print("  connected and its card profile is headset-head-unit, then retry.")
        return 1

    if args.text:
        FIXTURE_TXT.write_text(args.text.strip() + "\n")
        print(f"  expected: {FIXTURE_TXT}")

    print()
    print("  OK -- fixture captured. Next: tests/integration_test.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
