"""
Whisper v2 - Voice Keyboard

A voice keyboard that gets transcriptions from perception-voice server
and types them to the active window via keyboard simulation.
"""

import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
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
        self._clipboard_mode = False  # set by alt+space hotkey; cleared by ctrl+shift+space
        
        # Timestamp tracking for logging
        self.start_time = time.time()
        
        # Statistics
        self.transcription_count = 0

        # Buffer adjacent utterances so exact-match mappings only trigger after a pause
        self._pending_texts = []
        self._pending_last_ts: float | None = None
        self._normalized_command_mappings = {
            self._normalize_trigger_phrase(phrase): command
            for phrase, command in config.command_mappings.items()
        }
        self._normalized_activation_keywords = {
            self._normalize_trigger_phrase(phrase): action
            for phrase, action in config.activation_keywords.items()
        }
        self._output_enabled_at: float = 0.0
        self._command_shell = os.environ.get('SHELL') or '/bin/bash'
        
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

            def _to_pynput(hotkey_str: str) -> str:
                parts = [f"<{part.strip()}>" for part in hotkey_str.split('+')]
                return '+'.join(parts)

            hotkeys = {}

            sendkeys_str = config.toggle_listening_shortcut
            sendkeys_pynput = _to_pynput(sendkeys_str)
            self.log(f"Registering hotkey (sendkeys): {sendkeys_str} -> {sendkeys_pynput}")

            def on_activate_sendkeys():
                logger.debug("Sendkeys hotkey activated")
                self._clipboard_mode = False
                self.toggle_listening()

            hotkeys[sendkeys_pynput] = on_activate_sendkeys

            clipboard_str = config.toggle_listening_clipboard_shortcut
            if clipboard_str:
                clipboard_pynput = _to_pynput(clipboard_str)
                self.log(f"Registering hotkey (clipboard): {clipboard_str} -> {clipboard_pynput}")

                def on_activate_clipboard():
                    logger.debug("Clipboard hotkey activated")
                    self._clipboard_mode = True
                    self.toggle_listening()

                hotkeys[clipboard_pynput] = on_activate_clipboard

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
        
        # Tell the server to discard anything transcribed before this moment
        self.perception_client.set_read_marker()
        
        # Gate text output until the delay has elapsed (lets the key-press audio settle)
        delay = self.config.listening_state_delay_ms / 1000.0
        self._output_enabled_at = time.time() + delay
    
    def stop_listening(self):
        """Stop listening mode"""
        if not self.is_listening:
            return
        
        self.is_listening = False
        self.typer.cancel_pending_output()
        self._discard_pending_transcriptions()
        self.log("⏸️  Listening stopped")
        
        # Play sound
        if self.config.sounds_enabled:
            self.sound.play(self.config.sound_on_listening_stop)
    
    def _start_polling(self):
        """Start the always-on polling thread"""
        self._polling_stop_event.clear()
        self._polling_thread = threading.Thread(
            target=self._polling_loop,
            daemon=True,
            name="PerceptionVoicePoller"
        )
        self._polling_thread.start()
        logger.debug("Polling thread started")
    
    def _stop_polling(self, flush_pending: bool = True):
        """Stop the polling thread"""
        self._polling_stop_event.set()
        if self._polling_thread:
            self._polling_thread.join(timeout=1.0)
            self._polling_thread = None
        if flush_pending:
            self._flush_pending_transcriptions()
        else:
            self._discard_pending_transcriptions()
        logger.debug("Polling thread stopped")

    def _get_transcription_timestamp(self, item) -> float:
        """Get a comparable timestamp for a transcription item."""
        ts = item.get('ts')
        if ts:
            try:
                return datetime.fromisoformat(ts).timestamp()
            except ValueError:
                logger.debug(f"Could not parse transcription timestamp: {ts}")

        return time.time()

    def _normalize_trigger_phrase(self, text: str) -> str:
        """Normalize buffered text for exact-match command lookups."""
        normalized = re.sub(r'[^a-z]+', ' ', text.lower().strip())
        return re.sub(r'\s+', ' ', normalized).strip()

    def _get_command_mapping(self, text: str) -> str | None:
        """Return the configured shell command for an exact-match phrase."""
        return self._normalized_command_mappings.get(self._normalize_trigger_phrase(text))

    def _run_command_mapping(self, spoken_phrase: str, command: str):
        """Launch a configured shell command asynchronously."""
        try:
            if self.config.sounds_enabled:
                self.sound.play(self.config.sound_on_command_mapping)

            subprocess.Popen(
                command,
                shell=True,
                executable=self._command_shell,
                cwd=str(self.config.config_path.parent),
                start_new_session=True,
            )
            logger.info(f"Ran command mapping for {spoken_phrase!r}: {command}")
        except Exception as e:
            logger.error(f"Error running command mapping {spoken_phrase!r}: {e}")
            self.log(f"[Command Error]: {spoken_phrase}")

    def _match_activation_keyword(self, text: str) -> str | None:
        """Return the configured action for an always-on activation keyword, or None."""
        return self._normalized_activation_keywords.get(self._normalize_trigger_phrase(text))

    def _execute_activation_keyword(self, spoken_phrase: str, action: str):
        """Execute an activation keyword action (magic string or shell command)."""
        MAGIC_ACTIONS = frozenset({
            'LISTENING_ON', 'LISTENING_OFF', 'LISTENING_TOGGLE',
            'LISTENING_ON_CLIPBOARD', 'LISTENING_TOGGLE_CLIPBOARD',
        })
        if action in MAGIC_ACTIONS:
            if self.config.sounds_enabled:
                self.sound.play(self.config.sound_on_command_mapping)
            if action == 'LISTENING_ON':
                self._clipboard_mode = False
                self.start_listening()
            elif action == 'LISTENING_OFF':
                self.stop_listening()
            elif action == 'LISTENING_TOGGLE':
                self._clipboard_mode = False
                self.toggle_listening()
            elif action == 'LISTENING_ON_CLIPBOARD':
                self._clipboard_mode = True
                self.start_listening()
            elif action == 'LISTENING_TOGGLE_CLIPBOARD':
                self._clipboard_mode = True
                self.toggle_listening()
        else:
            # Treat as shell command (same as command_mappings)
            self._run_command_mapping(spoken_phrase, action)

    def _buffer_transcription(self, text: str, item_ts: float):
        """Add a transcription to the pending pause buffer."""
        if self._pending_last_ts is not None:
            gap = item_ts - self._pending_last_ts
            if gap >= self.config.word_mapping_pause_threshold_s:
                self._flush_pending_transcriptions()

        self._pending_texts.append(text)
        self._pending_last_ts = item_ts

    def _discard_pending_transcriptions(self):
        """Discard any buffered transcriptions without typing them."""
        self._pending_texts = []
        self._pending_last_ts = None

    def _flush_pending_transcriptions(self):
        """Emit any buffered transcriptions as raw text or an exact-match mapping."""
        if not self._pending_texts:
            return

        buffered_text = ' '.join(text.strip() for text in self._pending_texts if text.strip())
        self._pending_texts = []
        self._pending_last_ts = None

        if not buffered_text:
            return

        command = self._get_command_mapping(buffered_text)
        apply_word_mappings = self.typer.has_exact_word_mapping(buffered_text)

        self.transcription_count += 1
        if command:
            self.log(f"[Command]: {buffered_text}")
            self._run_command_mapping(buffered_text, command)
        elif self._clipboard_mode:
            self.log(f"[Clipboard]: {buffered_text}")
            self.typer.type_clipboard(buffered_text)
        elif apply_word_mappings:
            self.log(f"[Mapping]: {buffered_text}")
            self.typer.type_final(buffered_text, apply_word_mappings=True)
        else:
            self.log(f"[Typing]: {buffered_text}")
            self.typer.type_final(buffered_text, apply_word_mappings=False)

    def _flush_ready_buffer(self):
        """Flush pending text once the configured pause has elapsed."""
        if self._pending_last_ts is None:
            return

        if time.time() - self._pending_last_ts >= self.config.word_mapping_pause_threshold_s:
            self._flush_pending_transcriptions()
    
    def _polling_loop(self):
        """Poll perception-voice server for new transcriptions (always-on)"""
        interval = self.config.polling_interval_ms / 1000.0
        
        while not self._polling_stop_event.is_set():
            try:
                transcriptions = self.perception_client.get_transcriptions()
                output_ready = self.is_listening and time.time() >= self._output_enabled_at
                
                for item in transcriptions:
                    text = item.get('text', '')
                    
                    if not text:
                        continue
                    
                    # Always check activation keywords, even when not listening
                    action = self._match_activation_keyword(text)
                    if action is not None:
                        self.log(f"[Keyword]: {text} -> {action}")
                        self._execute_activation_keyword(text, action)
                        continue
                    
                    if not output_ready:
                        continue
                    
                    # Check if text should be discarded
                    if self.typer.should_discard(text):
                        self.log(f"[Discarded]: {text}")
                        continue

                    self._buffer_transcription(text, self._get_transcription_timestamp(item))

                if output_ready:
                    self._flush_ready_buffer()
            
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
        
        # Discard stale server transcriptions from before startup, then begin always-on polling
        self.perception_client.set_read_marker()
        self._start_polling()
        
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
        self._stop_polling(flush_pending=False)
        
        # Stop hotkey listener
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        
        # Stop keyboard typer
        if self.typer:
            self.typer.stop_queue_worker()
        
        self.log(f"✓ Total transcriptions: {self.transcription_count}")
        self.log("✓ Whisper v2 Voice Keyboard stopped")
