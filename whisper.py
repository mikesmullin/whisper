#!/usr/bin/env python3
"""
Whisper - Voice Keyboard

A cross-platform voice keyboard that transcribes speech to typed text.
"""

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import torch
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard

# Import custom modules
from lib.config import Config
from lib.keyboard_output import KeyboardTyper
from lib.tray import SystemTray, TRAY_AVAILABLE

logger = logging.getLogger(__name__)


class VoiceKeyboard:
    """Voice keyboard with speech-to-text transcription"""
    
    def __init__(
        self,
        config: Config,
        verbose: bool = False,
        headless: bool = False
    ):
        """
        Initialize voice keyboard
        
        Args:
            config: Configuration object
            verbose: Print transcriptions to stdout
            headless: Run without system tray
        """
        self.config = config
        self.verbose = verbose
        self.headless = headless
        
        self.is_running = False
        self.is_listening = False
        self.sample_rate = config.sample_rate
        
        # Buffers for audio processing
        self.mic_buffer = []
        self.mic_vad_buffer = []
        self.mic_is_speaking = False
        self.mic_silence_count = 0
        
        self.max_silence_chunks = config.silence_chunks
        self.vad_chunk_size = 512
        
        # Statistics
        self.transcription_count = 0
        
        # Audio level tracking for verbose mode
        self.mic_level = 0.0
        self.level_lock = threading.Lock()
        
        # Load models
        self._load_models()
        
        # Initialize keyboard typer
        self.typer = KeyboardTyper(word_mappings=config.word_mappings)
        
        # Initialize system tray (if not headless)
        self.tray = None
        if not headless and TRAY_AVAILABLE and config.system_tray_enabled:
            self.tray = SystemTray(
                on_toggle=self.toggle_listening,
                on_quit=self.quit,
                notifications_enabled=config.notifications_enabled
            )
        
        # Setup keyboard hotkeys
        self._setup_hotkeys()
        
        print("✓ Whisper Voice Keyboard initialized")
    
    def _load_models(self):
        """Load VAD and Whisper models"""
        print("Loading models...")
        
        # Load Silero VAD
        self.vad_model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            verbose=False
        )
        print("✓ VAD loaded")
        
        # Load Whisper
        self.whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        print("✓ Whisper loaded")
    
    def _setup_hotkeys(self):
        """Setup keyboard hotkeys"""
        try:
            toggle_key = self.config.toggle_on_shortcut
            
            # Convert from "ctrl+shift+space" to "<ctrl>+<shift>+<space>" format for pynput
            # pynput requires angle brackets around each key
            pynput_format = '+'.join(f'<{key}>' for key in toggle_key.split('+'))
            
            logger.info(f"Registering hotkey: {toggle_key} -> {pynput_format}")
            
            # Use pynput's global hotkey listener
            from pynput.keyboard import GlobalHotKeys
            
            def on_activate():
                logger.info("Hotkey activated!")
                self.toggle_listening()
            
            hotkeys = {
                pynput_format: on_activate
            }
            
            self.hotkey_listener = GlobalHotKeys(hotkeys)
            self.hotkey_listener.start()
            
            print(f"✓ Hotkey registered: {toggle_key}")
        
        except Exception as e:
            import traceback
            logger.error(f"Failed to register hotkey: {e}")
            logger.error(traceback.format_exc())
            logger.warning("You can still toggle listening using the system tray menu")
            self.hotkey_listener = None
    
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
        print("🎤 Listening started")
        
        # Update tray icon
        if self.tray:
            self.tray.set_listening(True)
            self.tray.update_menu(True)
            if self.config.get('notifications.show_on_toggle', True):
                self.tray.notify("Whisper", "Listening started")
    
    def stop_listening(self):
        """Stop listening to microphone"""
        if not self.is_listening:
            return
        
        self.is_listening = False
        print("⏸️  Listening stopped")
        
        # Update tray icon
        if self.tray:
            self.tray.set_listening(False)
            self.tray.update_menu(False)
            if self.config.get('notifications.show_on_toggle', True):
                self.tray.notify("Whisper", "Listening stopped")
    
    def process_mic_audio(self, audio_chunk):
        """Process microphone audio with VAD"""
        if not self.is_listening:
            return
        
        try:
            # Update audio level for verbose mode
            if self.verbose:
                rms = np.sqrt(np.mean(audio_chunk ** 2))
                with self.level_lock:
                    self.mic_level = rms
            
            audio_tensor = torch.from_numpy(audio_chunk).float()
            with torch.no_grad():
                speech_prob = self.vad_model(audio_tensor, self.sample_rate).item()
            
            is_speech = speech_prob > 0.5
            
            if is_speech:
                if not self.mic_is_speaking:
                    logger.debug(f"🎤 Speech detected ({speech_prob:.3f})")
                    self.mic_is_speaking = True
                
                self.mic_buffer.append(audio_chunk)
                self.mic_silence_count = 0
            else:
                if self.mic_is_speaking:
                    self.mic_silence_count += 1
                    self.mic_buffer.append(audio_chunk)
                    
                    if self.mic_silence_count >= self.max_silence_chunks:
                        complete_audio = np.concatenate(self.mic_buffer)
                        duration = len(complete_audio) / self.sample_rate
                        
                        # Skip very short utterances
                        if duration >= self.config.min_utterance_duration:
                            logger.debug(f"📝 Speech ended ({duration:.1f}s)")
                            threading.Thread(
                                target=self.transcribe_and_type,
                                args=(complete_audio,),
                                daemon=True
                            ).start()
                        
                        self.mic_buffer = []
                        self.mic_is_speaking = False
                        self.mic_silence_count = 0
        
        except Exception as e:
            logger.error(f"Error processing mic audio: {e}")
    
    def transcribe_and_type(self, audio):
        """Transcribe audio and type it"""
        try:
            # Transcribe
            segments, info = self.whisper_model.transcribe(
                audio,
                language="en",
                beam_size=5
            )
            
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())
            
            full_text = " ".join(text_parts)
            
            if not full_text:
                return
            
            self.transcription_count += 1
            
            # Print to stdout if verbose
            if self.verbose:
                print(f"[Transcribed]: {full_text}")
                sys.stdout.flush()
            
            # Type the text
            self.typer.type_text(full_text)
        
        except Exception as e:
            logger.error(f"Error in transcription: {e}")
    
    def start(self):
        """Start the voice keyboard"""
        self.is_running = True
        
        # Start microphone stream
        mic_device = self.config.mic_device
        if mic_device is None:
            mic_device = auto_detect_microphone()
            if mic_device is None:
                print("Error: Could not auto-detect microphone")
                return False
        
        thread = threading.Thread(
            target=self._run_mic_stream,
            args=(mic_device,),
            daemon=True
        )
        thread.start()
        print(f"✓ Microphone stream ready (device #{mic_device})")
        
        # Start system tray
        if self.tray:
            self.tray.run_detached()
            if self.config.get('notifications.show_on_start', True):
                self.tray.notify("Whisper", "Voice keyboard ready")
        
        if self.verbose:
            print("\n🎙️  Ready! Use hotkey to toggle listening... (Ctrl+C to quit)\n")
        else:
            print("\n🎙️  Ready! Use hotkey to toggle listening... (Ctrl+C to quit)\n")
        
        # Keep running
        try:
            while self.is_running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n⏹️  Stopping...")
            self.quit()
        
        return True
    
    def _run_mic_stream(self, device_index):
        """Run microphone stream"""
        def callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Mic status: {status}")
            
            audio_chunk = indata[:, 0].copy()
            self.process_mic_audio(audio_chunk)
        
        try:
            with sd.InputStream(
                device=device_index,
                channels=1,
                samplerate=self.sample_rate,
                blocksize=512,
                callback=callback
            ):
                while self.is_running:
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Microphone stream error: {e}")
    
    def quit(self):
        """Stop the voice keyboard"""
        self.is_running = False
        self.is_listening = False
        
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        
        if self.tray:
            self.tray.stop()
        
        print(f"\n✓ Total transcriptions: {self.transcription_count}")
        print("✓ Whisper Voice Keyboard stopped")


def auto_detect_microphone():
    """Auto-detect default microphone"""
    try:
        default_idx = sd.default.device[0]
        device_info = sd.query_devices(default_idx)
        if device_info['max_input_channels'] > 0:
            print(f"✓ Auto-detected microphone: [{default_idx}] {device_info['name']}")
            return default_idx
    except:
        pass
    
    # Fallback: find first microphone
    devices = sd.query_devices()
    for idx, device in enumerate(devices):
        if device['max_input_channels'] > 0 and (
            'microphone' in device['name'].lower() or 
            'headset' in device['name'].lower() or
            'mic' in device['name'].lower()
        ):
            print(f"✓ Auto-detected microphone: [{idx}] {device['name']}")
            return idx
    
    return None


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
  
  # Run without system tray
  whisper --headless
  
  # Generate default config file
  whisper --generate-config
  
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
        help='Configuration file path (default: ~/.whisper.yaml)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print transcriptions to stdout'
    )
    
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run without system tray'
    )
    
    parser.add_argument(
        '--generate-config',
        action='store_true',
        help='Generate default configuration file and exit'
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
    
    # Override mic device if specified
    if args.mic is not None:
        config.config['audio']['mic_device'] = args.mic
    
    # Generate config and exit if requested
    if args.generate_config:
        if config.save_default_config():
            print(f"✓ Default configuration saved to {config.config_path}")
            print(f"  Edit this file to customize settings")
        else:
            print(f"✗ Failed to save configuration")
        sys.exit(0)
    
    # Create voice keyboard
    voice_keyboard = VoiceKeyboard(
        config=config,
        verbose=args.verbose,
        headless=args.headless
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
