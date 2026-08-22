"""
Keyboard output for typing transcriptions
"""

import logging
import queue
import re
import threading
import time
from typing import Dict, Optional, Set

from pynput.keyboard import Controller, Key, KeyCode

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
        self._normalized_word_mappings = {
            self._normalize_mapping_phrase(phrase): replacement
            for phrase, replacement in self.word_mappings.items()
        }
        
        # Discard filter: phrases that should not be typed
        if discard_phrases is None:
            self.discard_phrases = DEFAULT_DISCARD_PHRASES
        else:
            self.discard_phrases = {p.lower().strip() for p in discard_phrases}
        
        # Output queue for serializing keyboard output
        self._output_queue: queue.Queue = queue.Queue()
        self._queue_worker_thread: Optional[threading.Thread] = None
        self._queue_running = False
        self._cancel_output_event = threading.Event()
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
                    self._do_type_final(
                        task["text"],
                        task["delay"],
                        task.get("apply_word_mappings", True)
                    )
                elif task_type == "type_clipboard":
                    self._do_type_clipboard(task["text"])
                else:
                    logger.warning(f"Unknown queue task type: {task_type}")
            
            except Exception as e:
                logger.error(f"Error processing keyboard queue task: {e}")
            finally:
                self._output_queue.task_done()
    
    def stop_queue_worker(self):
        """Stop the queue worker thread (for cleanup)"""
        self.cancel_pending_output()
        self._queue_running = False
        if self._queue_worker_thread:
            self._queue_worker_thread.join(timeout=2.0)
            self._queue_worker_thread = None
        logger.debug("Keyboard output queue worker stopped")

    def cancel_pending_output(self):
        """Cancel queued and in-flight keyboard output immediately."""
        self._cancel_output_event.set()

        while True:
            try:
                self._output_queue.get_nowait()
                self._output_queue.task_done()
            except queue.Empty:
                break

        logger.debug("Cancelled pending keyboard output")
    
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
    
    def type_clipboard(self, text: str):
        """
        Queue text to be written to the clipboard then pasted via Ctrl+V.

        Word-mapping text substitutions are applied; hotkey-type mappings are
        executed via pynput as usual.  Only the text portions go to the
        clipboard so the paste is atomic.

        Args:
            text: Final transcription text
        """
        if not text:
            return

        self._cancel_output_event.clear()
        self._output_queue.put({
            "type": "type_clipboard",
            "text": text,
        })

    def _xclip_read(self) -> bytes | None:
        """Return current clipboard contents as bytes, or None on failure."""
        import subprocess
        try:
            proc = subprocess.run(
                ['xclip', '-selection', 'clipboard', '-o'],
                capture_output=True,
            )
            # xclip exits non-zero when clipboard is empty; treat that as b''
            return proc.stdout
        except FileNotFoundError:
            logger.error("xclip not found; install it with: sudo apt install xclip")
            return None
        except Exception as e:
            logger.warning(f"Clipboard read failed: {e}")
            return None

    def _xclip_write(self, data: bytes) -> bool:
        """Write bytes to the clipboard. Returns True on success."""
        import subprocess
        try:
            proc = subprocess.Popen(
                ['xclip', '-selection', 'clipboard'],
                stdin=subprocess.PIPE,
            )
            proc.communicate(data)
            if proc.returncode != 0:
                logger.error(f"xclip write failed with return code {proc.returncode}")
                return False
            return True
        except FileNotFoundError:
            logger.error("xclip not found; install it with: sudo apt install xclip")
            return False
        except Exception as e:
            logger.error(f"Clipboard write failed: {e}")
            return False

    def _do_type_clipboard(self, text: str):
        """
        Write processed text to the clipboard (via xclip) then send Ctrl+V,
        restoring the previous clipboard contents afterwards.

        Args:
            text: Final transcription text (word mappings will be applied)
        """
        processed_items = self._process_text(text, apply_word_mappings=True)

        # Collect text portions; execute hotkey items normally
        text_parts = []
        for item in processed_items:
            if self._cancel_output_event.is_set():
                logger.debug("Clipboard output cancelled")
                return
            if isinstance(item, dict) and 'hotkey' in item:
                self._execute_hotkey(item['hotkey'])
            else:
                text_parts.append(item)

        # Append trailing space the same way the sendkeys path does
        combined = ''.join(text_parts)
        if combined and not combined.endswith(('\n', '\r')):
            combined += ' '

        if not combined or self._cancel_output_event.is_set():
            return

        # Backup existing clipboard contents (None means xclip unavailable)
        previous = self._xclip_read()

        if not self._xclip_write(combined.encode('utf-8')):
            return

        if self._cancel_output_event.is_set():
            self._xclip_write(previous if previous is not None else b'')
            return

        # Paste
        self._execute_hotkey('ctrl+v')
        logger.info(f"Clipboard-pasted: {repr(combined)}")

        # Restore previous clipboard contents
        self._xclip_write(previous if previous is not None else b'')

    def type_final(
        self,
        text: str,
        delay: Optional[float] = None,
        apply_word_mappings: bool = True
    ):
        """
        Queue final transcription for typing with word mappings applied.
        
        Args:
            text: Final transcription text
            delay: Delay between characters in seconds (uses default if None)
            apply_word_mappings: Whether configured word mappings should be applied
        """
        if not text:
            return

        self._cancel_output_event.clear()
        
        self._output_queue.put({
            "type": "type_final",
            "text": text,
            "delay": delay if delay is not None else self.typing_delay_s,
            "apply_word_mappings": apply_word_mappings,
        })
    
    def _do_type_final(self, text: str, delay: float, apply_word_mappings: bool):
        """
        Actually type final transcription with word mappings applied.
        
        Args:
            text: Final transcription text
            delay: Delay between characters in seconds
            apply_word_mappings: Whether configured word mappings should be applied
        """
        # Process text and apply word mappings
        processed_items = self._process_text(text, apply_word_mappings)
        should_append_space = self._should_append_trailing_space(processed_items)
        
        logger.debug(f"Processed items: {repr(processed_items)}")
        
        try:
            for item in processed_items:
                if self._cancel_output_event.is_set():
                    logger.debug("Keyboard output cancelled before item completed")
                    return

                if isinstance(item, dict) and 'hotkey' in item:
                    self._execute_hotkey(item['hotkey'])
                else:
                    prev_char = None
                    for char in item:
                        if self._cancel_output_event.is_set():
                            logger.debug("Keyboard output cancelled during text typing")
                            return

                        # When the same key is typed back-to-back, the USB HID host
                        # may not see the key-up report before the next key-down if
                        # the gap is only one polling interval (~8ms at 125Hz).
                        # Ensure at least 20ms (2.5x the polling interval) of
                        # key-up visibility, regardless of typing_delay_ms setting.
                        if char == prev_char:
                            time.sleep(max(self.typing_delay_s, 0.020))

                        self._type_char(char)
                        prev_char = char
                        if delay > 0:
                            time.sleep(delay)
            
            if should_append_space and not self._cancel_output_event.is_set():
                # Append a space after final transcription unless output ends with a newline
                self._type_char(' ')
            
            logger.info(f"Typed: {repr(text)}")
        
        except Exception as e:
            logger.error(f"Error typing text: {e}")

    def has_exact_word_mapping(self, text: str) -> bool:
        """Return whether text exactly matches a configured mapping trigger."""
        return self._normalize_mapping_phrase(text) in self._normalized_word_mappings

    def _should_append_trailing_space(self, processed_items) -> bool:
        """Return whether final output should get the default trailing space."""
        for item in reversed(processed_items):
            if isinstance(item, dict):
                continue

            if not item:
                continue

            return not item.endswith(('\n', '\r'))

        return True

    def _normalize_mapping_phrase(self, text: str) -> str:
        """Normalize text for exact mapping-trigger matching."""
        return re.sub(r'^[\s\.,!?;:]+|[\s\.,!?;:]+$', '', text.lower().strip())

    def _process_text(self, text: str, apply_word_mappings: bool):
        """Normalize final text and optionally apply configured mappings."""
        text = re.sub(r'\.\s*$', '', text)

        if not apply_word_mappings:
            return [text] if text else []

        return self._apply_word_mappings(text)
    
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

                # Check if replacement is a hotkey (before placeholder
                # resolution, since resolved clipboard content could
                # otherwise coincidentally look like one)
                if '+' in replacement and len(replacement) < 20:
                    items.append({'hotkey': replacement})
                elif replacement:
                    items.append(self._resolve_placeholders(replacement))
            elif part.strip():
                items.append(part)

        return items if items else [text]

    def _resolve_placeholders(self, text: str) -> str:
        """Resolve {{clipboard}} placeholders in a word-mapping replacement."""
        if '{{clipboard}}' not in text:
            return text

        data = self._xclip_read()
        clipboard_text = data.decode('utf-8', errors='replace') if data else ''
        return text.replace('{{clipboard}}', clipboard_text)
    
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
                elif len(key) == 1:
                    # Same XTEST-vs-XSendEvent issue as _type_char: a bare
                    # character would be sent via XSendEvent and ignored by
                    # GTK4 apps, so ctrl+z would arrive as a lone ctrl.
                    pynput_keys.append(self._char_key(key))
                else:
                    pynput_keys.append(key)
            
            logger.info(f"Executing hotkey: {hotkey_str}")
            
            # Press all keys
            for key in pynput_keys:
                if self._cancel_output_event.is_set():
                    logger.debug("Keyboard hotkey cancelled before key press")
                    return
                self.controller.press(key)
                time.sleep(0.01)
            
            # Release all keys in reverse order
            for key in reversed(pynput_keys):
                self.controller.release(key)
                time.sleep(0.01)
            
            logger.debug(f"Hotkey executed: {hotkey_str}")
        
        except Exception as e:
            logger.error(f"Error executing hotkey {hotkey_str}: {e}")
    
    # Mapping of shifted characters to their base keys (US keyboard layout)
    # When typing these characters, we need to explicitly press Shift + base_key
    # so that SDL2-based applications (like kvm-client) see the proper scancode + modifier
    SHIFTED_CHAR_MAP = {
        '~': '`', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
        '^': '6', '&': '7', '*': '8', '(': '9', ')': '0', '_': '-',
        '+': '=', '{': '[', '}': ']', '|': '\\', ':': ';', '"': "'",
        '<': ',', '>': '.', '?': '/',
    }

    SPECIAL_CHAR_KEY_MAP = {
        '\n': Key.enter,
        '\r': Key.enter,
        '\t': Key.tab,
    }
    
    @staticmethod
    def _char_key(char: str) -> KeyCode:
        """
        Build a KeyCode carrying an explicit vk (X keysym) for a character.

        pynput's X11 backend picks its injection mechanism per key: a KeyCode
        with vk set is sent via XTEST fake_input, while one without falls back
        to XSendEvent.  GTK4 applications (Ghostty) discard XSendEvent key
        events as forged, so characters typed the default way never arrive --
        only Key.* constants (space, enter, tab), which carry a vk, get
        through.  Supplying the keysym forces every character onto XTEST.

        For printable ASCII the X keysym equals the code point; other
        codepoints use the Unicode keysym offset.
        """
        cp = ord(char)
        return KeyCode.from_vk(cp if cp < 0x80 else 0x01000000 + cp)

    def _type_char(self, char: str):
        """
        Type a single character using explicit press/release.
        
        For shifted characters (like ? ! @ etc.), explicitly presses Shift + base_key
        so that SDL2-based applications see the proper scancode with modifier.
        
        Args:
            char: Character to type
        """
        try:
            if self._cancel_output_event.is_set():
                return

            # Check if this is a shifted character that needs explicit Shift + base_key
            if char in self.SPECIAL_CHAR_KEY_MAP:
                key = self.SPECIAL_CHAR_KEY_MAP[char]
                self.controller.press(key)
                if self.key_hold_s > 0:
                    time.sleep(self.key_hold_s)
                self.controller.release(key)
            elif char in self.SHIFTED_CHAR_MAP:
                base_key = self._char_key(self.SHIFTED_CHAR_MAP[char])
                self.controller.press(Key.shift)
                time.sleep(0.005)  # Small delay to ensure shift is registered
                self.controller.press(base_key)
                if self.key_hold_s > 0:
                    time.sleep(self.key_hold_s)
                self.controller.release(base_key)
                time.sleep(0.005)
                self.controller.release(Key.shift)
            elif char.isupper() and char.isalpha():
                # Uppercase letters also need explicit Shift
                base_key = self._char_key(char.lower())
                self.controller.press(Key.shift)
                time.sleep(0.005)
                self.controller.press(base_key)
                if self.key_hold_s > 0:
                    time.sleep(self.key_hold_s)
                self.controller.release(base_key)
                time.sleep(0.005)
                self.controller.release(Key.shift)
            elif char == ' ':
                self.controller.press(Key.space)
                if self.key_hold_s > 0:
                    time.sleep(self.key_hold_s)
                self.controller.release(Key.space)
            else:
                key = self._char_key(char)
                self.controller.press(key)
                if self.key_hold_s > 0:
                    time.sleep(self.key_hold_s)
                self.controller.release(key)
            
            if self.typing_delay_s > 0:
                time.sleep(self.typing_delay_s)
        
        except Exception as e:
            logger.warning(f"Could not type character {repr(char)}: {e}")
