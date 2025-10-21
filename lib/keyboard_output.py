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
        
        # Process text and apply word mappings
        processed_text = self._apply_word_mappings(text)
        
        logger.debug(f"Processed text: {repr(processed_text)}")
        
        # Type the processed text
        try:
            for char in processed_text:
                self._type_char(char)
                if delay > 0:
                    time.sleep(delay)
            
            logger.info(f"Typed: {processed_text[:50]}{'...' if len(processed_text) > 50 else ''}")
        
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
        
        # First, strip trailing period if it exists (unless "period" or "dot" is in the mapping)
        # This removes auto-added periods from Whisper
        has_period_mapping = any(word.lower() in ['period', 'dot'] for word in self.word_mappings.keys())
        if not has_period_mapping:
            # Remove trailing period that Whisper adds
            text = re.sub(r'\.\s*$', '', text)
        
        # Replace mapped words
        result = text
        for word, replacement in self.word_mappings.items():
            # Create a regex pattern that matches the word with optional punctuation
            # Match word with trailing punctuation (comma, period, etc.) or whitespace
            pattern = rf'\b{re.escape(word)}[,.\s]*'
            # Replace with the mapped value (no space added, the replacement itself controls formatting)
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        
        # Clean up any double spaces
        result = re.sub(r' +', ' ', result)
        
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
