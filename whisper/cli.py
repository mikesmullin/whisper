"""
Whisper v2 CLI entry point
"""

import argparse
import logging
import signal
import sys
from pathlib import Path

from whisper.config import Config
from whisper.voice_keyboard import VoiceKeyboard


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
        help='Configuration file path (default: config.yaml in workspace root)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
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
        voice_keyboard.quit()
        sys.exit(0)
    
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
