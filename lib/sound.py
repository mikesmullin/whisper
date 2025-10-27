"""
Sound playback for audio feedback
"""

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class SoundPlayer:
    """Plays sound files for user feedback"""
    
    def __init__(self, enabled: bool = True):
        """
        Initialize sound player
        
        Args:
            enabled: Whether sound playback is enabled
        """
        self.enabled = enabled
        self._player = None
        
        # Try to import a sound library
        try:
            import winsound
            self._player = 'winsound'
            logger.debug("Using winsound for audio playback")
        except ImportError:
            try:
                import pygame
                pygame.mixer.init()
                self._player = 'pygame'
                logger.debug("Using pygame for audio playback")
            except ImportError:
                try:
                    import playsound
                    self._player = 'playsound'
                    logger.debug("Using playsound for audio playback")
                except ImportError:
                    logger.warning("No sound library available (winsound/pygame/playsound)")
                    self.enabled = False
    
    def play(self, filepath: str, async_play: bool = True):
        """
        Play a sound file
        
        Args:
            filepath: Path to the .wav file
            async_play: Whether to play asynchronously (non-blocking)
        """
        if not self.enabled or not self._player:
            return
        
        # Check if file exists
        if not os.path.exists(filepath):
            logger.debug(f"Sound file not found: {filepath} (skipping)")
            return
        
        if async_play:
            # Play in background thread to avoid blocking
            thread = threading.Thread(target=self._play_sync, args=(filepath,), daemon=True)
            thread.start()
        else:
            self._play_sync(filepath)
    
    def _play_sync(self, filepath: str):
        """
        Play sound synchronously
        
        Args:
            filepath: Path to the sound file
        """
        try:
            if self._player == 'winsound':
                import winsound
                winsound.PlaySound(filepath, winsound.SND_FILENAME)
            elif self._player == 'pygame':
                import pygame
                sound = pygame.mixer.Sound(filepath)
                sound.play()
            elif self._player == 'playsound':
                from playsound import playsound
                playsound(filepath)
            
            logger.debug(f"Played sound: {filepath}")
        except Exception as e:
            logger.error(f"Error playing sound {filepath}: {e}")
