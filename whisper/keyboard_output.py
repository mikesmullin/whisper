"""
Keyboard output for typing transcriptions
"""

import logging
import queue
import re
import threading
import time
from typing import Dict, Optional, Set

from pynput.keyboard import Controller, Key

logger = logging.getLogger(__name__)


# Default phrases to discard (commonly misheard sounds)
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
            key_hold_ms: Delay in milliseconds between key press and release
            discard_phrases: Set of phrases to discard (case-insensitive)
        """
        self.controller = Controller()
        self.word_mappings = word_mappings or {}
        self.typing_delay_ms = typing_delay_ms
        self.typing_delay_s = typing_delay_ms / 1000.0
        self.key_hold_ms = key_hold_ms
        self.key_hold_s = key_hold_ms / 1000.0
        
        # Discard filter: phrases that should not be typed
        if discard_phrases is None:
            self.discard_phrases = DEFAULT_DISCARD_PHRASES
        else:
            self.discard_phrases = {p.lower().strip() for p in discard_phrases}
        
        # Output queue for serializing keyboard output
        self._output_queue: queue.Queue = queue.Queue()
        self._queue_worker_thread: Optional[threading.Thread] = None
        self._queue_running = False
        self._start_queue_worker()
        
        logger.info(f"Keyboard typer initialized with {len(self.word_mappings)} mappings")
        logger.info(f"Discard filter has {len(self.discard_phrases)} phrases")
    
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
                task = self._output_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            
            try:
                task_type = task.get("type")
                
                if task_type == "type_final":
                    self._do_type_final(task["text"], task["delay"])
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
            True if the text matches a discard phrase
        """
        if not text:
            return True
        
        # Normalize: lowercase, strip whitespace and punctuation
        normalized = re.sub(r'^[\s\.,!?;:]+|[\s\.,!?;:]+$', '', text.lower().strip())
        
        if normalized in self.discard_phrases:
            logger.info(f"Discarding text: {repr(text)} -> {repr(normalized)}")
            return True
        
        return False
    
    def type_final(self, text: str, delay: Optional[float] = None):
        """
        Queue final transcription for typing with word mappings applied.
        
        Args:
            text: Final transcription text
            delay: Delay between characters in seconds (uses default if None)
        """
        if not text:
            return
        
        self._output_queue.put({
            "type": "type_final",
            "text": text,
            "delay": delay if delay is not None else self.typing_delay_s
        })
    
    def _do_type_final(self, text: str, delay: float):
        """
        Actually type final transcription with word mappings applied.
        
        Args:
            text: Final transcription text
            delay: Delay between characters in seconds
        """
        # Process text and apply word mappings
        processed_items = self._apply_word_mappings(text)
        
        logger.debug(f"Processed items: {repr(processed_items)}")
        
        try:
            for item in processed_items:
                if isinstance(item, dict) and 'hotkey' in item:
                    self._execute_hotkey(item['hotkey'])
                else:
                    for char in item:
                        self._type_char(char)
                        if delay > 0:
                            time.sleep(delay)
            
            # Append a space after final transcription
            self._type_char(' ')
            
            logger.info(f"Typed: {repr(text)}")
        
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
        text = re.sub(r'\.\s*$', '', text)
        
        # Sort mappings by length (longest first) to avoid partial matches
        sorted_mappings = sorted(
            self.word_mappings.items(),
            key=lambda x: len(x[0]),
            reverse=True
        )
        
        # Build replacements with markers
        replacements = {}
        marker_counter = 0
        result_text = text
        
        for word, replacement in sorted_mappings:
            pattern = rf'\b{re.escape(word)}\b[,.\s]*'
            
            def replace_func(match, counter=marker_counter, repl=replacement):
                nonlocal marker_counter
                marker = f"<<<MARKER_{counter}>>>"
                replacements[marker] = repl
                marker_counter += 1
                return marker
            
            result_text = re.sub(pattern, replace_func, result_text, flags=re.IGNORECASE)
        
        # Split by markers and build final list
        items = []
        parts = re.split(r'(<<<MARKER_\d+>>>)', result_text)
        
        for part in parts:
            if part.startswith('<<<MARKER_'):
                replacement = replacements.get(part, '')
                
                # Check if replacement is a hotkey
                if '+' in replacement and len(replacement) < 20:
                    items.append({'hotkey': replacement})
                elif replacement:
                    items.append(replacement)
            elif part.strip():
                items.append(part)
        
        return items if items else [text]
    
    def _execute_hotkey(self, hotkey_str: str):
        """
        Execute a hotkey combination
        
        Args:
            hotkey_str: Hotkey string like "ctrl+z" or "ctrl+shift+s"
        """
        try:
            keys = hotkey_str.lower().split('+')
            
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
            
            pynput_keys = []
            for key in keys:
                if key in key_map:
                    pynput_keys.append(key_map[key])
                else:
                    pynput_keys.append(key)
            
            logger.info(f"Executing hotkey: {hotkey_str}")
            
            # Press all keys
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
        Type a single character using explicit press/release
        
        Args:
            char: Character to type
        """
        try:
            if char == ' ':
                self.controller.press(Key.space)
            else:
                self.controller.press(char)
            
            if self.key_hold_s > 0:
                time.sleep(self.key_hold_s)
            
            if char == ' ':
                self.controller.release(Key.space)
            else:
                self.controller.release(char)
            
            if self.typing_delay_s > 0:
                time.sleep(self.typing_delay_s)
        
        except Exception as e:
            logger.warning(f"Could not type character {repr(char)}: {e}")
