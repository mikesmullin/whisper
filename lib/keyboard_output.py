"""
Keyboard output for typing transcriptions
"""

import logging
import re
import time
from typing import Dict, Optional
from pynput.keyboard import Controller, Key

logger = logging.getLogger(__name__)


class KeyboardTyper:
    """Types transcribed text using keyboard simulation"""
    
    def __init__(self, word_mappings: Optional[Dict[str, str]] = None):
        """
        Initialize keyboard typer
        
        Args:
            word_mappings: Dictionary mapping spoken words to keyboard inputs
        """
        self.controller = Controller()
        self.word_mappings = word_mappings or {}
        
        logger.info(f"Keyboard typer initialized with {len(self.word_mappings)} word mappings")
        for word, replacement in self.word_mappings.items():
            logger.debug(f"  Mapping: {repr(word)} -> {repr(replacement)}")
    
    def type_text(self, text: str, delay: float = 0.01):
        """
        Type text with word mapping support
        
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
        
        # First, strip trailing period if it exists (unless "period" or "dot" is in the mapping)
        # This removes auto-added periods from Whisper
        has_period_mapping = any(word.lower() in ['period', 'dot'] for word in self.word_mappings.keys())
        if not has_period_mapping:
            # Remove trailing period that Whisper adds
            text = re.sub(r'\.\s*$', '', text)
        
        # Build a list of items (text segments and hotkey commands) to process
        items = []
        remaining_text = text
        
        # Sort mappings by length (longest first) to avoid partial matches
        sorted_mappings = sorted(self.word_mappings.items(), key=lambda x: len(x[0]), reverse=True)
        
        while remaining_text:
            matched = False
            
            for word, replacement in sorted_mappings:
                # Match word with optional trailing punctuation
                pattern = rf'^(.*?)\b{re.escape(word)}\b[,.\s]*(.*)$'
                match = re.search(pattern, remaining_text, flags=re.IGNORECASE)
                
                if match:
                    before, after = match.groups()
                    
                    # Add text before the match
                    if before.strip():
                        items.append(before)
                    
                    # Check if replacement is a hotkey (format: "ctrl+z")
                    if '+' in replacement and len(replacement) < 20:
                        # Likely a hotkey
                        items.append({'hotkey': replacement})
                    else:
                        # Regular text replacement
                        items.append(replacement)
                    
                    remaining_text = after
                    matched = True
                    break
            
            if not matched:
                # No more matches, add remaining text
                if remaining_text.strip():
                    items.append(remaining_text)
                break
        
        # Clean up: merge adjacent text items and remove empty items
        merged_items = []
        for item in items:
            if isinstance(item, dict):
                merged_items.append(item)
            elif item.strip():
                if merged_items and isinstance(merged_items[-1], str):
                    merged_items[-1] += item
                else:
                    merged_items.append(item)
        
        return merged_items if merged_items else [text]
    
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
        Type a single character, handling special characters
        
        Args:
            char: Character to type
        """
        try:
            self.controller.type(char)
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
        Press the Backspace key
        
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
