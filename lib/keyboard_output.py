"""
Keyboard output for typing transcriptions
"""

import logging
import queue
import re
import threading
import time
from typing import Callable, Dict, List, Optional, Set
from pynput.keyboard import Controller, Key

logger = logging.getLogger(__name__)


# Default phrases to discard (commonly misheard sounds like coughs/sneezes)
DEFAULT_DISCARD_PHRASES: Set[str] = {
    "thank you",
    "thanks",
    "you",
}


class KeyboardTyper:
    """Types transcribed text using keyboard simulation with queued output"""
    
    def __init__(
        self,
        word_mappings: Optional[Dict[str, str]] = None,
        typing_delay_ms: int = 10,
        key_hold_ms: int = 20,
        discard_phrases: Optional[Set[str]] = None
    ):
        """
        Initialize keyboard typer
        
        Args:
            word_mappings: Dictionary mapping spoken words to keyboard inputs
            typing_delay_ms: Delay in milliseconds between each keystroke
            key_hold_ms: Delay in milliseconds between key press and release (for SDL2 compatibility)
            discard_phrases: Set of phrases to discard (case-insensitive). If None, uses defaults.
        """
        self.controller = Controller()
        self.word_mappings = word_mappings or {}
        self.typing_delay_ms = typing_delay_ms
        self.typing_delay_s = typing_delay_ms / 1000.0  # Convert to seconds
        self.key_hold_ms = key_hold_ms
        self.key_hold_s = key_hold_ms / 1000.0  # Convert to seconds
        
        # Preview mode tracking
        self.preview_length = 0  # Number of characters in current preview
        self.last_preview_text = ""
        
        # Discard filter: phrases that should not be typed (normalized to lowercase)
        if discard_phrases is None:
            self.discard_phrases = DEFAULT_DISCARD_PHRASES
        else:
            self.discard_phrases = {p.lower().strip() for p in discard_phrases}
        
        # Output queue for serializing keyboard output (prevents interleaving)
        self._output_queue: queue.Queue = queue.Queue()
        self._queue_worker_thread: Optional[threading.Thread] = None
        self._queue_running = False
        self._start_queue_worker()
        
        logger.info(f"Keyboard typer initialized with {len(self.word_mappings)} word mappings")
        logger.info(f"Discard filter has {len(self.discard_phrases)} phrases: {self.discard_phrases}")
        for word, replacement in self.word_mappings.items():
            logger.debug(f"  Mapping: {repr(word)} -> {repr(replacement)}")
    
    def _start_queue_worker(self):
        """Start the background worker thread that processes the output queue"""
        if self._queue_running:
            return
        
        self._queue_running = True
        self._queue_worker_thread = threading.Thread(
            target=self._queue_worker_loop,
            daemon=True,
            name="KeyboardOutputQueue"
        )
        self._queue_worker_thread.start()
        logger.debug("Keyboard output queue worker started")
    
    def _queue_worker_loop(self):
        """Background worker that processes queued keyboard output tasks"""
        while self._queue_running:
            try:
                # Block with timeout to allow graceful shutdown
                task = self._output_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            
            try:
                task_type = task.get("type")
                
                if task_type == "type_text":
                    self._do_type_text(task["text"], task["delay"])
                elif task_type == "type_final":
                    self._do_type_final(task["text"], task["delay"])
                elif task_type == "type_preview":
                    self._do_type_realtime_preview(task["text"])
                elif task_type == "backspace":
                    self._do_press_backspace(task["count"])
                else:
                    logger.warning(f"Unknown queue task type: {task_type}")
            except Exception as e:
                logger.error(f"Error processing keyboard queue task: {e}")
            finally:
                self._output_queue.task_done()
    
    def stop_queue_worker(self):
        """Stop the queue worker thread (for cleanup)"""
        self._queue_running = False
        if self._queue_worker_thread:
            self._queue_worker_thread.join(timeout=2.0)
            self._queue_worker_thread = None
        logger.debug("Keyboard output queue worker stopped")
    
    def should_discard(self, text: str) -> bool:
        """
        Check if the text should be discarded based on the discard filter.
        
        Args:
            text: Text to check
            
        Returns:
            True if the text matches a discard phrase and should be dropped
        """
        if not text:
            return True
        
        # Normalize: lowercase, strip whitespace and punctuation
        normalized = re.sub(r'^[\s\.,!?;:]+|[\s\.,!?;:]+$', '', text.lower().strip())
        
        # Check if normalized text matches any discard phrase
        if normalized in self.discard_phrases:
            logger.info(f"Discarding text that matches filter: {repr(text)} -> {repr(normalized)}")
            return True
        
        return False

    def type_text(self, text: str, delay: float = 0.01):
        """
        Queue text for typing with word mapping support.
        Text is added to a queue and typed in order (prevents interleaving).
        
        Args:
            text: Text to type
            delay: Delay between characters in seconds
        """
        if not text:
            return
        
        self._output_queue.put({
            "type": "type_text",
            "text": text,
            "delay": delay
        })
    
    def _do_type_text(self, text: str, delay: float = 0.01):
        """
        Actually type text with word mapping support (called by queue worker).
        
        Args:
            text: Text to type
            delay: Delay between characters in seconds
        """
        if not text:
            return
        
        logger.debug(f"Original text: {repr(text)}")
        
        # Process text and apply word mappings (returns list of strings or hotkey commands)
        processed_items = self._apply_word_mappings(text)
        
        logger.debug(f"Processed items: {repr(processed_items)}")
        
        # Type the processed text or execute hotkeys
        try:
            for item in processed_items:
                if isinstance(item, dict) and 'hotkey' in item:
                    # Execute hotkey
                    self._execute_hotkey(item['hotkey'])
                else:
                    # Type regular text
                    for char in item:
                        self._type_char(char)
                        if delay > 0:
                            time.sleep(delay)
            
            logger.info(f"Completed typing/hotkey execution")
        
        except Exception as e:
            logger.error(f"Error typing text: {e}")
    
    def _apply_word_mappings(self, text: str):
        """
        Apply word mappings to text
        
        Args:
            text: Input text
            
        Returns:
            List of strings or hotkey commands to execute in order
        """
        if not self.word_mappings:
            return [text]
        
        # Always strip trailing period - Whisper adds them automatically
        # Users can explicitly say "end of sentence" or "dot" to add periods
        text = re.sub(r'\.\s*$', '', text)
        
        # Sort mappings by length (longest first) to avoid partial matches
        sorted_mappings = sorted(self.word_mappings.items(), key=lambda x: len(x[0]), reverse=True)
        
        # Build a pattern that matches any of the mapped words
        # We'll use a marker to track replacements
        replacements = {}
        marker_counter = 0
        result_text = text
        
        for word, replacement in sorted_mappings:
            # Match word with optional trailing punctuation/whitespace
            pattern = rf'\b{re.escape(word)}\b[,.\s]*'
            
            def replace_func(match):
                nonlocal marker_counter
                marker = f"<<<MARKER_{marker_counter}>>>"
                replacements[marker] = replacement
                marker_counter += 1
                return marker
            
            result_text = re.sub(pattern, replace_func, result_text, flags=re.IGNORECASE)
        
        # Now split the result by markers and build the final list
        items = []
        parts = re.split(r'(<<<MARKER_\d+>>>)', result_text)
        
        for part in parts:
            if part.startswith('<<<MARKER_'):
                # This is a marker - replace with actual value
                replacement = replacements.get(part, '')
                
                # Check if replacement is a hotkey (format: "ctrl+z")
                if '+' in replacement and len(replacement) < 20:
                    # Likely a hotkey
                    items.append({'hotkey': replacement})
                else:
                    # Regular text replacement
                    if replacement:
                        items.append(replacement)
            else:
                # Regular text
                if part.strip():
                    items.append(part)
        
        return items if items else [text]
    
    def _execute_hotkey(self, hotkey_str: str):
        """
        Execute a hotkey combination
        
        Args:
            hotkey_str: Hotkey string like "ctrl+z" or "ctrl+shift+s"
        """
        try:
            # Parse hotkey string
            keys = hotkey_str.lower().split('+')
            
            # Map string names to pynput Key objects
            key_map = {
                'ctrl': Key.ctrl,
                'control': Key.ctrl,
                'shift': Key.shift,
                'alt': Key.alt,
                'cmd': Key.cmd,
                'win': Key.cmd,
                'super': Key.cmd,
                'enter': Key.enter,
                'tab': Key.tab,
                'esc': Key.esc,
                'escape': Key.esc,
                'backspace': Key.backspace,
                'delete': Key.delete,
                'space': Key.space,
            }
            
            # Convert keys to pynput Key objects or characters
            pynput_keys = []
            for key in keys:
                if key in key_map:
                    pynput_keys.append(key_map[key])
                else:
                    # Single character key
                    pynput_keys.append(key)
            
            logger.info(f"Executing hotkey: {hotkey_str}")
            
            # Press all keys in order
            for key in pynput_keys:
                self.controller.press(key)
                time.sleep(0.01)
            
            # Release all keys in reverse order
            for key in reversed(pynput_keys):
                self.controller.release(key)
                time.sleep(0.01)
            
            logger.debug(f"Hotkey executed: {hotkey_str}")
        
        except Exception as e:
            logger.error(f"Error executing hotkey {hotkey_str}: {e}")
    
    def _type_char(self, char: str):
        """
        Type a single character using explicit press/release for SDL2 compatibility
        
        Args:
            char: Character to type
        """
        try:
            # Use explicit press/release with configurable hold time
            # to ensure reliable key event delivery to SDL2 and similar apps
            if char == ' ':
                self.controller.press(Key.space)
            else:
                self.controller.press(char)
            
            # Hold the key for reliable detection
            if self.key_hold_s > 0:
                time.sleep(self.key_hold_s)
            
            if char == ' ':
                self.controller.release(Key.space)
            else:
                self.controller.release(char)
            
            # Add delay between keystrokes to prevent skipping in some inputs
            if self.typing_delay_s > 0:
                time.sleep(self.typing_delay_s)
        except Exception as e:
            # If pynput can't type it directly, log and skip
            logger.warning(f"Could not type character {repr(char)}: {e}")
    
    def press_enter(self):
        """Press the Enter key"""
        try:
            self.controller.press(Key.enter)
            self.controller.release(Key.enter)
            logger.debug("Pressed Enter")
        except Exception as e:
            logger.error(f"Error pressing Enter: {e}")
    
    def press_tab(self):
        """Press the Tab key"""
        try:
            self.controller.press(Key.tab)
            self.controller.release(Key.tab)
            logger.debug("Pressed Tab")
        except Exception as e:
            logger.error(f"Error pressing Tab: {e}")
    
    def press_backspace(self, count: int = 1):
        """
        Queue backspace key presses.
        
        Args:
            count: Number of times to press backspace
        """
        if count <= 0:
            return
        
        self._output_queue.put({
            "type": "backspace",
            "count": count
        })
    
    def _do_press_backspace(self, count: int = 1):
        """
        Actually press the Backspace key (called by queue worker).
        
        Args:
            count: Number of times to press backspace
        """
        try:
            for _ in range(count):
                self.controller.press(Key.backspace)
                self.controller.release(Key.backspace)
                time.sleep(0.01)
            logger.debug(f"Pressed Backspace {count} time(s)")
        except Exception as e:
            logger.error(f"Error pressing Backspace: {e}")
    
    def type_realtime_preview(self, text: str):
        """
        Queue realtime preview text for typing (unstable, will be replaced by final).
        
        This is for showing instant feedback during speech. The text is typed
        without word mappings applied, and will be cleared when final transcription
        arrives or when preview updates.
        
        Args:
            text: Preview text to type
        """
        if not text:
            return
        
        self._output_queue.put({
            "type": "type_preview",
            "text": text
        })
    
    def _do_type_realtime_preview(self, text: str):
        """
        Actually type realtime preview text (called by queue worker).
        
        Args:
            text: Preview text to type
        """
        if not text:
            return
        
        # Clear previous preview if it exists
        if self.preview_length > 0:
            self._do_press_backspace(self.preview_length)
            self.preview_length = 0
        
        # Type new preview (no word mappings, just raw text)
        try:
            for char in text:
                self._type_char(char)
            
            self.preview_length = len(text)
            self.last_preview_text = text
            logger.debug(f"Preview typed: {repr(text)}")
        
        except Exception as e:
            logger.error(f"Error typing preview: {e}")
            self.preview_length = 0
    
    def type_final(self, text: str, delay: float = 0.01):
        """
        Queue final transcription for typing with word mappings applied.
        
        This replaces any existing preview and applies word mappings.
        A trailing space is appended to prevent word conjoining when dictation resumes.
        
        Args:
            text: Final transcription text
            delay: Delay between characters in seconds
        """
        if not text:
            return
        
        self._output_queue.put({
            "type": "type_final",
            "text": text,
            "delay": delay
        })
    
    def _do_type_final(self, text: str, delay: float = 0.01):
        """
        Actually type final transcription with word mappings applied (called by queue worker).
        
        Args:
            text: Final transcription text
            delay: Delay between characters in seconds
        """
        # Clear preview if exists
        if self.preview_length > 0:
            self._do_press_backspace(self.preview_length)
            self.preview_length = 0
            self.last_preview_text = ""
        
        # Type final text with word mappings (directly, not via queue since we're already in queue worker)
        self._do_type_text(text, delay)
        
        # Append a space after final transcription to prevent word conjoining
        # when dictation resumes after a pause
        self._type_char(' ')
        
        logger.debug(f"Final typed: {repr(text)}")
