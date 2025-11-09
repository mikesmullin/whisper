#!/usr/bin/env python3
"""
Whisper - Voice Keyboard

A cross-platform voice keyboard that transcribes speech to typed text.
Refactored to use dual-model system with realtime preview.
"""

import argparse
import logging
import signal
import sys
import threading
import time
import platform
from pathlib import Path

import numpy as np

# Import custom modules
from lib.config import Config
from lib.keyboard_output import KeyboardTyper
from lib.audio_recorder import AudioRecorder
from lib.sound import SoundPlayer

logger = logging.getLogger(__name__)


class VoiceKeyboard:
    """Voice keyboard with speech-to-text transcription"""
    
    def __init__(
        self,
        config: Config,
        verbose: bool = False
    ):
        """
        Initialize voice keyboard
        
        Args:
            config: Configuration object
            verbose: Print transcriptions to stdout
        """
        self.config = config
        self.verbose = verbose or config.verbose_logging
        
        self.is_running = False
        self.is_listening = False
        
        # Timestamp tracking for logging
        self.start_time = time.time()
        
        # Statistics
        self.transcription_count = 0
        
        # Initialize sound player
        self.sound = SoundPlayer(enabled=config.sounds_enabled)
        
        # Initialize keyboard typer
        # Initialize keyboard typer
        self.typer = KeyboardTyper(
            word_mappings=config.word_mappings,
            typing_delay_ms=config.typing_delay_ms
        )
        
        # Initialize audio recorder with callbacks
        self.log("Initializing audio recorder...")
        self.recorder = AudioRecorder(
            # Model configuration
            model=config.model,
            realtime_model=config.realtime_model,
            language=config.language,
            device=config.device,
            compute_type=config.compute_type,
            
            # VAD configuration
            webrtc_sensitivity=config.webrtc_sensitivity,
            silero_sensitivity=config.silero_sensitivity,
            silero_use_onnx=config.silero_use_onnx,
            
            # Audio configuration
            sample_rate=config.sample_rate,
            buffer_size=config.buffer_size,
            mic_device=config.mic_device,
            
            # Timing configuration
            min_length_of_recording=config.min_utterance_duration,
            post_speech_silence_duration=config.post_speech_silence_duration,
            pre_recording_buffer_duration=config.pre_recording_buffer_duration,
            
            # Realtime transcription
            enable_realtime_transcription=config.enable_realtime_transcription,
            realtime_processing_pause=config.realtime_processing_pause,
            
            # Beam search
            beam_size=config.beam_size,
            beam_size_realtime=config.beam_size_realtime,
            
            # Callbacks
            on_recording_start=self.on_recording_start,
            on_recording_stop=self.on_recording_stop,
            on_realtime_transcription_update=self.on_realtime_update,
            on_transcription_complete=self.on_final_transcription,
            
            # Logging
            verbose=self.verbose
        )
        
        # Setup hotkey listener
        self.hotkey_listener = None
        if config.toggle_listening_shortcut:
            from pynput.keyboard import GlobalHotKeys
            
            # Parse hotkey combination
            hotkey_str = config.toggle_listening_shortcut
            
            # Convert our format to pynput format
            # "ctrl+shift+space" -> "<ctrl>+<shift>+<space>"
            parts = [f"<{part.strip()}>" for part in hotkey_str.split('+')]
            pynput_hotkey = '+'.join(parts)
            
            self.log(f"Registering hotkey: {hotkey_str} -> {pynput_hotkey}")
            
            # Use pynput's GlobalHotKeys for reliable hotkey detection
            def on_activate():
                logger.debug("Hotkey activated!")
                self.toggle_listening()
            
            hotkeys = {
                pynput_hotkey: on_activate
            }
            
            self.hotkey_listener = GlobalHotKeys(hotkeys)
        
        self.log("✓ Whisper Voice Keyboard initialized")
    
    def log(self, message: str):
        """Log message with optional timestamp"""
        if self.config.timestamps_enabled:
            elapsed = time.time() - self.start_time
            seconds = int(elapsed)
            milliseconds = int((elapsed - seconds) * 1000)
            timestamp = f"{seconds}.{milliseconds:03d}s "
            print(f"{timestamp}{message}")
        else:
            print(message)
        
        sys.stdout.flush()
    
    def on_recording_start(self):
        """Callback when recording starts"""
        self.log("🎤 Speech detected")
    
    def on_recording_stop(self):
        """Callback when recording stops"""
        self.log("⏸️  Speech ended")
    
    def on_realtime_update(self, text: str):
        """Callback for realtime preview updates"""
        # Don't process if listening is stopped
        if not self.is_listening:
            return
        
        if self.verbose:
            self.log(f"[Preview]: {text}")
        
        # Type preview to keyboard only if enabled (causes backspace corrections)
        if self.config.type_realtime_preview:
            self.typer.type_realtime_preview(text)
    
    def on_final_transcription(self, text: str):
        """Callback for final accurate transcription"""
        # Don't process if listening is stopped (transcription was cancelled)
        if not self.is_listening:
            self.log(f"[Cancelled]: {text}")
            return
        
        self.transcription_count += 1
        self.log(f"[Final]: {text}")
        
        # Type final text with word mappings
        self.typer.type_final(text)
    
    def toggle_listening(self):
        """Toggle listening state"""
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()
    
    def start_listening(self):
        """Start listening to microphone"""
        if self.is_listening:
            return
        
        self.is_listening = True
        self.log("🎤 Listening started")
        
        # Resume audio recorder (unpause VAD)
        self.recorder.resume()
        
        # Play sound
        if self.config.sounds_enabled:
            self.sound.play(self.config.sound_on_listening_start)
    
    def stop_listening(self):
        """Stop listening to microphone"""
        if not self.is_listening:
            return
        
        self.is_listening = False
        self.log("⏸️  Listening stopped")
        
        # Pause audio recorder (stop VAD processing)
        self.recorder.pause()
        
        # Play sound
        if self.config.sounds_enabled:
            self.sound.play(self.config.sound_on_listening_stop)
    
    def start(self):
        """Start the voice keyboard"""
        self.is_running = True
        
        # Start audio recorder (in paused state initially)
        self.recorder.start()
        self.recorder.pause()  # Start paused, user presses hotkey to begin
        self.log("✓ Audio recorder ready")
        
        # Start hotkey listener
        if self.hotkey_listener:
            self.hotkey_listener.start()
            self.log(f"✓ Hotkey monitoring enabled ({self.config.toggle_listening_shortcut} = toggle listening)")
        
        if self.verbose:
            self.log(f"🎙️  Ready! Press {self.config.toggle_listening_shortcut} to toggle listening... (Ctrl+C to quit)")
        else:
            self.log("🎙️  Ready! (Ctrl+C to quit)")
        
        # Keep running
        try:
            while self.is_running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.log("\n⏹️  Stopping...")
            self.quit()
        
        return True
    
    def quit(self):
        """Stop the voice keyboard"""
        self.is_running = False
        self.is_listening = False
        
        # Stop hotkey listener
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        
        # Stop audio recorder
        if self.recorder:
            self.recorder.stop()
        
        self.log(f"✓ Total transcriptions: {self.transcription_count}")
        self.log("✓ Whisper Voice Keyboard stopped")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Whisper - Voice Keyboard for cross-platform speech-to-text typing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default config
  whisper
  
  # Run in verbose mode (show transcriptions)
  whisper --verbose
  
  # Use specific microphone device
  whisper --mic 1
        """
    )
    
    parser.add_argument(
        '-m', '--mic',
        type=int,
        metavar='N',
        help='Microphone device index (auto-detect if not provided)'
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
        help='Print transcriptions to stdout'
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
    print("Whisper - Voice Keyboard")
    print("=" * 60)
    
    # Load configuration
    config_path = Path(args.config) if args.config else None
    config = Config(config_path)
    
    # Auto-generate config.yaml if it doesn't exist
    if not config.config_path.exists():
        print(f"No configuration file found at {config.config_path}")
        print(f"Generating default configuration...")
        if config.save_default_config():
            print(f"✓ Default configuration saved to {config.config_path}")
            print(f"  Edit this file to customize settings")
            # Reload config after creating it
            config = Config(config_path)
        else:
            print(f"✗ Failed to save configuration, using defaults")
    
    # Override mic device if specified
    if args.mic is not None:
        config.config['audio']['mic_device'] = args.mic
    
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
