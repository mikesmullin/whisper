#!/usr/bin/env python3
"""
Startup-reliability integration test for perception-voice + whisper.

One iteration:

  1. restart both systemd user units
  2. wait until the server is *actually ready* -- IPC socket bound AND
     mic audio callbacks firing (proved by live `levels` frames)
  3. inject the recorded speech fixture through a PipeWire virtual mic,
     which the services see as the ordinary ALSA `default` device
  4. wait for the finalized transcription over IPC and compare it to the
     fixture's expected text

Pass criteria: every iteration transcribes the fixture, and time-to-ready
stays under --target-ready seconds.

    tests/record_fixture.py --text "..."      # once, to capture the fixture
    tests/integration_test.py --runs 10

Modes:
    --mode virtual   inject the fixture (default; fully automatic)
    --mode real      keep the real microphone; assert readiness and that
                     capture is live, without injecting audio
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness as H  # noqa: E402
from virtual_mic import VirtualMic  # noqa: E402

UID = "whisper-integration-test"


def preflight(mode: str) -> list[str]:
    problems = []
    for tool in ("systemctl", "pactl", "pw-play", "pw-loopback"):
        if not subprocess.run(["sh", "-c", f"command -v {tool}"],
                              capture_output=True).stdout:
            problems.append(f"missing required tool: {tool}")
    if not H.PERCEPTION_BIN.exists():
        problems.append(f"perception-voice not found at {H.PERCEPTION_BIN}")
    if mode == "virtual":
        if not H.FIXTURE_WAV.exists():
            problems.append(
                f"no fixture at {H.FIXTURE_WAV} -- run tests/record_fixture.py first"
            )
        elif H.wav_peak_dbfs(H.FIXTURE_WAV) < -40.0:
            problems.append(
                f"fixture {H.FIXTURE_WAV} is silence "
                f"({H.wav_peak_dbfs(H.FIXTURE_WAV):.1f} dBFS peak) -- re-record it"
            )
        else:
            try:
                H.prepare_injection_wav()
            except Exception as e:
                problems.append(f"could not prepare the injection wav: {e}")
        if not H.FIXTURE_TXT.exists():
            problems.append(
                f"no expected transcript at {H.FIXTURE_TXT} -- re-run "
                "tests/record_fixture.py with --text"
            )
    return problems


def whisper_saw_text(since: str) -> str:
    """Lines whisper logged after `since` showing it acted on transcriptions."""
    out = subprocess.run(
        ["journalctl", "--user", "-u", "whisper", "--since", since,
         "--no-pager", "-o", "cat"],
        capture_output=True, text=True,
    ).stdout
    return "\n".join(
        line for line in out.split("\n")
        if any(tag in line for tag in ("[Typing]", "[Mapping]", "[Clipboard]",
                                       "[Command]", "[Keyword]"))
    )


def run_iteration(n: int, args, mic: VirtualMic | None, expected: str) -> H.Iteration:
    wall_since = time.strftime("%Y-%m-%d %H:%M:%S")

    t0 = H.restart_units()
    ready = H.wait_for_audio_frames(timeout=args.timeout_ready)
    if ready is None:
        return H.Iteration(n, None, None, "", 0.0, False,
                           "never became ready (no mic audio frames)")
    ready_s = time.monotonic() - t0

    if mic is None:
        level = H.measure_level(duration=1.0)
        live = level is not None
        return H.Iteration(n, ready_s, None, "", 0.0, live,
                           f"capture live, mean level {level:.3f}" if live
                           else "no level data")

    # Discard anything buffered before this moment, exactly as whisper does.
    if not H.set_marker(UID):
        return H.Iteration(n, ready_s, None, "", 0.0, False,
                           "could not set read marker")

    t_play = time.monotonic()
    mic.play(H.FIXTURE_INJECT_WAV)

    deadline = time.monotonic() + args.timeout_transcribe
    items: list[dict] = []
    while time.monotonic() < deadline:
        items = H.get_transcriptions(UID)
        if items:
            break
        time.sleep(0.05)

    if not items:
        return H.Iteration(n, ready_s, None, "", 0.0, False,
                           "audio injected but nothing transcribed")

    transcribe_s = time.monotonic() - t_play
    text = " ".join(i.get("text", "") for i in items).strip()
    overlap = H.word_overlap(expected, text)
    ok = overlap >= args.min_overlap

    note = ""
    if args.check_whisper:
        seen = whisper_saw_text(wall_since)
        note = "whisper acted on it" if seen else "whisper logged no output"
        if args.require_whisper and not seen:
            ok = False

    return H.Iteration(n, ready_s, transcribe_s, text, overlap, ok, note)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--mode", choices=("virtual", "real"), default="virtual")
    ap.add_argument("--timeout-ready", type=float, default=30.0,
                    help="give up on readiness after this many seconds")
    ap.add_argument("--timeout-transcribe", type=float, default=25.0)
    ap.add_argument("--target-ready", type=float, default=3.0,
                    help="time-to-ready budget; exceeding it fails the run")
    ap.add_argument("--min-overlap", type=float, default=0.6,
                    help="fraction of expected words that must appear")
    ap.add_argument("--check-whisper", action="store_true",
                    help="also report whether whisper logged typed output")
    ap.add_argument("--require-whisper", action="store_true",
                    help="fail an iteration if whisper logged no output "
                         "(needs listening to be latched on)")
    args = ap.parse_args()

    problems = preflight(args.mode)
    if problems:
        print("Preflight failed:")
        for p in problems:
            print(f"  - {p}")
        return 2

    expected = H.FIXTURE_TXT.read_text().strip() if H.FIXTURE_TXT.exists() else ""

    print(f"mode={args.mode}  runs={args.runs}  "
          f"ready budget={args.target_ready:g}s")
    if args.mode == "virtual":
        print(f"fixture: {H.FIXTURE_WAV} "
              f"({H.wav_duration(H.FIXTURE_WAV):.1f}s, "
              f"{H.wav_rms_dbfs(H.FIXTURE_WAV):.0f} dBFS RMS as recorded)")
        print(f"injected: {H.FIXTURE_INJECT_WAV.name} "
              f"({H.wav_duration(H.FIXTURE_INJECT_WAV):.1f}s incl. silence pads, "
              f"normalized to {H.wav_rms_dbfs(H.FIXTURE_INJECT_WAV):.0f} dBFS RMS)")
        print(f"expected: {expected!r}")
    print()
    header = f"{'run':>3}  {'ready':>7}  {'stt':>7}  {'match':>6}  result"
    print(header)
    print("-" * max(len(header), 60))

    results: list[H.Iteration] = []

    def report(it: H.Iteration) -> None:
        ready = f"{it.ready_s:.2f}s" if it.ready_s is not None else "  --  "
        stt = f"{it.transcribe_s:.2f}s" if it.transcribe_s is not None else "  --  "
        match = f"{it.overlap * 100:.0f}%" if it.transcribe_s is not None else "  -- "
        verdict = "PASS" if it.ok else "FAIL"
        detail = it.note or (it.text[:48] if it.text else "")
        print(f"{it.n:>3}  {ready:>7}  {stt:>7}  {match:>6}  {verdict}"
              f"{'  ' + detail if detail else ''}", flush=True)

    mic_ctx = VirtualMic() if args.mode == "virtual" else None
    try:
        if mic_ctx:
            mic_ctx.__enter__()
        for n in range(1, args.runs + 1):
            it = run_iteration(n, args, mic_ctx, expected)
            results.append(it)
            report(it)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        if mic_ctx:
            mic_ctx.__exit__(None, None, None)

    if not results:
        return 1

    passed = [r for r in results if r.ok]
    readies = [r.ready_s for r in results if r.ready_s is not None]
    over_budget = [r for r in results
                   if r.ready_s is not None and r.ready_s > args.target_ready]

    print()
    print(f"transcribed: {len(passed)}/{len(results)}")
    if readies:
        print(f"time-to-ready: median {statistics.median(readies):.2f}s  "
              f"min {min(readies):.2f}s  max {max(readies):.2f}s  "
              f"(budget {args.target_ready:g}s)")
        print(f"over budget: {len(over_budget)}/{len(results)}")

    ok = len(passed) == len(results) and not over_budget
    print()
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
