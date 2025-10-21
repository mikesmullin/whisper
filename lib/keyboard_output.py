"""
Keyboard output for typing transcriptions
"""

import logging
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
    
    def type_text(self, text: str, delay: float = 0.01):
        """
        Type text with word mapping support
        
        Args:
            text: Text to type
            delay: Delay between characters in seconds
        """
        if not text:
            return
        
        # Process text and apply word mappings
        processed_text = self._apply_word_mappings(text)
        
        # Type the processed text
        try:
            for char in processed_text:
                self._type_char(char)
                if delay > 0:
                    time.sleep(delay)
            
            logger.debug(f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}")
        
        except Exception as e:
            logger.error(f"Error typing text: {e}")
    
    def _apply_word_mappings(self, text: str) -> str:
        """
        Apply word mappings to text
        
        Args:
            text: Input text
            
        Returns:
            Text with word mappings applied
        """
        if not self.word_mappings:
            return text
        
        # Replace mapped words
        result = text
        for word, replacement in self.word_mappings.items():
            # Try to match whole words (with spaces around them)
            # Also match at start/end of string
            result = result.replace(f" {word} ", f" {replacement} ")
            result = result.replace(f" {word}.", f" {replacement}.")
            result = result.replace(f" {word},", f" {replacement},")
            
            # Handle case where word is at the start or end
            if result.startswith(f"{word} "):
                result = f"{replacement} " + result[len(word) + 1:]
            if result.endswith(f" {word}"):
                result = result[:-len(word) - 1] + f" {replacement}"
            
            # Exact match
            if result == word:
                result = replacement
        
        return result
    
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
