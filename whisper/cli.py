"""
Whisper v2 CLI entry point
"""
import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

from whisper.config import Config
from whisper.voice_keyboard import VoiceKeyboard


def _dump_all_stacks() -> str:
    """Python stacks of all live threads (diagnostic; called on shutdown hang)."""
    lines = [f"=== python stacks of all threads at {time.strftime('%Y-%m-%d %H:%M:%S')} ==="]
    try:
        frames = sys._current_frames()
    except Exception:
        frames = {}
    for tid, frame in frames.items():
        chain = []
        f = frame
        while f is not None:
            try:
                chain.append(
                    f"    {f.f_code.co_filename.rsplit('/', 1)[-1]}:{f.f_lineno} in {f.f_code.co_name}"
                )
            except Exception:
                chain.append("    (unmappable frame)")
            f = getattr(f, "f_back", None)
        chain.reverse()
        lines.append(f"--- T{tid} ---")
        lines.extend(chain)
    return "\n".join(lines)


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Whisper v2 - Voice Keyboard via perception-voice",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default config
  whisper
  
  # Run in verbose mode
  whisper --verbose
  
Prerequisites:
  perception-voice serve must be running
        """
    )

    parser.add_argument(
        '-c', '--config',
        type=str,
        metavar='FILE',
        help="Configuration file path (default: config.yaml in workspace root)"
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    print("=" * 60)
    print("Whisper v2 - Voice Keyboard")
    print("=" * 60)

    # Load configuration
    config_path = Path(args.config) if args.config else None
    config = Config(config_path)

    # Create voice keyboard
    voice_keyboard = VoiceKeyboard(
        config=config,
        verbose=args.verbose
    )

    # Setup signal handler
    def signal_handler(sig, frame):
        def hard_exit(code):
            """Dump all Python stacks (diagnostic) and terminate the process
            immediately — without running Python finalization, which is the
            source of intermittent shutdown hangs (C-extension / thread
            teardown)."""
            try:
                with open("/tmp/whisper-shutdown-stuck.txt", "w") as fh:
                    fh.write(_dump_all_stacks() + "\n")
            except Exception:
                pass
            os._exit(code)

        # Safety net: if cleanup below hangs, bail out deterministically
        # (with a stack dump for diagnosis) after 3 seconds.
        watchdog = threading.Timer(3.0, hard_exit, args=(130,))
        watchdog.daemon = False
        watchdog.start()

        try:
            voice_keyboard.quit()
        except Exception as e:
            # Cleanup itself failed — log it and bail hard.
            print(f"Error during shutdown: {e}", file=sys.stderr)
            hard_exit(1)
            return

        # Cleanup finished cleanly. Flush the streams (already flushed per
        # line, but be explicit) and terminate without Python finalization.
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start voice keyboard
    try:
        voice_keyboard.start()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
