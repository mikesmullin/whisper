"""
Whisper v2 - Voice Keyboard

A voice keyboard that gets transcriptions from perception-voice server
and types them to the active window via keyboard simulation.
"""

import logging
import signal
import sys
import threading
import time
from pathlib import Path

from whisper.config import Config
from whisper.keyboard_output import KeyboardTyper
from whisper.perception_client import PerceptionVoiceClient
from whisper.sound import SoundPlayer

logger = logging.getLogger(__name__)


class VoiceKeyboard:
    """Voice keyboard with speech-to-text via perception-voice"""
    
    def __init__(self, config: Config, verbose: bool = False):
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
        
        # Polling thread
        self._polling_thread: threading.Thread = None
        self._polling_stop_event = threading.Event()
        
        # Initialize perception-voice client
        self.perception_client = PerceptionVoiceClient(config.socket_path)
        
        # Initialize sound player
        self.sound = SoundPlayer(
            enabled=config.sounds_enabled,
            base_path=config.config_path.parent
        )
        
        # Initialize keyboard typer
        self.typer = KeyboardTyper(
            word_mappings=config.word_mappings,
            typing_delay_ms=config.typing_delay_ms,
            key_hold_ms=config.key_hold_ms,
            discard_phrases=config.discard_phrases
        )
        
        # Setup hotkey listener
        self.hotkey_listener = None
        if config.toggle_listening_shortcut:
            from pynput.keyboard import GlobalHotKeys
            
            hotkey_str = config.toggle_listening_shortcut
            
            # Convert our format to pynput format
            # "ctrl+shift+space" -> "<ctrl>+<shift>+<space>"
            parts = [f"<{part.strip()}>" for part in hotkey_str.split('+')]
            pynput_hotkey = '+'.join(parts)
            
            self.log(f"Registering hotkey: {hotkey_str} -> {pynput_hotkey}")
            
            def on_activate():
                logger.debug("Hotkey activated!")
                self.toggle_listening()
            
            hotkeys = {pynput_hotkey: on_activate}
            self.hotkey_listener = GlobalHotKeys(hotkeys)
        
        self.log("✓ Whisper v2 Voice Keyboard initialized")
    
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
    
    def toggle_listening(self):
        """Toggle listening state"""
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()
    
    def start_listening(self):
        """Start listening mode"""
        if self.is_listening:
            return
        
        # Check if perception-voice server is running
        if not self.perception_client.is_server_running():
            self.log("❌ perception-voice server not running!")
            return
        
        self.is_listening = True
        self.log("🎤 Listening started")
        
        # Play sound
        if self.config.sounds_enabled:
            self.sound.play(self.config.sound_on_listening_start)
        
        # Set read marker to now (discard any old transcriptions)
        if not self.perception_client.set_read_marker():
            self.log("⚠️  Failed to set read marker")
        
        # Start polling after delay
        delay = self.config.listening_state_delay_ms / 1000.0
        threading.Timer(delay, self._start_polling).start()
    
    def stop_listening(self):
        """Stop listening mode"""
        if not self.is_listening:
            return
        
        self.is_listening = False
        self.log("⏸️  Listening stopped")
        
        # Play sound
        if self.config.sounds_enabled:
            self.sound.play(self.config.sound_on_listening_stop)
        
        # Stop polling
        self._stop_polling()
    
    def _start_polling(self):
        """Start the polling thread"""
        if not self.is_listening:
            return
        
        self._polling_stop_event.clear()
        self._polling_thread = threading.Thread(
            target=self._polling_loop,
            daemon=True,
            name="PerceptionVoicePoller"
        )
        self._polling_thread.start()
        logger.debug("Polling thread started")
    
    def _stop_polling(self):
        """Stop the polling thread"""
        self._polling_stop_event.set()
        if self._polling_thread:
            self._polling_thread.join(timeout=1.0)
            self._polling_thread = None
        logger.debug("Polling thread stopped")
    
    def _polling_loop(self):
        """Poll perception-voice server for new transcriptions"""
        interval = self.config.polling_interval_ms / 1000.0
        
        while not self._polling_stop_event.is_set() and self.is_listening:
            try:
                transcriptions = self.perception_client.get_transcriptions()
                
                for item in transcriptions:
                    # Check if we should still process (user might have stopped)
                    if not self.is_listening:
                        self.log(f"[Cancelled]: {item.get('text', '')}")
                        break
                    
                    text = item.get('text', '')
                    
                    if not text:
                        continue
                    
                    # Check if text should be discarded
                    if self.typer.should_discard(text):
                        self.log(f"[Discarded]: {text}")
                        continue
                    
                    self.transcription_count += 1
                    self.log(f"[Typing]: {text}")
                    
                    # Type the text
                    self.typer.type_final(text)
            
            except Exception as e:
                logger.error(f"Polling error: {e}")
            
            # Wait for next poll
            self._polling_stop_event.wait(interval)
    
    def start(self):
        """Start the voice keyboard"""
        self.is_running = True
        
        # Check if perception-voice server is running
        if not self.perception_client.is_server_running():
            self.log(f"⚠️  perception-voice server not found at {self.config.socket_path}")
            self.log("   Make sure perception-voice serve is running")
        else:
            self.log("✓ perception-voice server detected")
        
        # Start hotkey listener
        if self.hotkey_listener:
            self.hotkey_listener.start()
            self.log(f"✓ Hotkey enabled: {self.config.toggle_listening_shortcut}")
        
        if self.verbose:
            self.log("🎙️  Ready! Press hotkey to toggle listening... (Ctrl+C to quit)")
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
        
        # Stop polling
        self._stop_polling()
        
        # Stop hotkey listener
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        
        # Stop keyboard typer
        if self.typer:
            self.typer.stop_queue_worker()
        
        self.log(f"✓ Total transcriptions: {self.transcription_count}")
        self.log("✓ Whisper v2 Voice Keyboard stopped")
