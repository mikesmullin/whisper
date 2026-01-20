"""
Sound playback for audio feedback
"""

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SoundPlayer:
    """Plays sound files for user feedback"""
    
    def __init__(self, enabled: bool = True, base_path: Optional[Path] = None):
        """
        Initialize sound player
        
        Args:
            enabled: Whether sound playback is enabled
            base_path: Base directory for resolving relative sound file paths
        """
        self.enabled = enabled
        self._player = None
        self.base_path = base_path or Path.cwd()
        
        # Try to find a suitable audio player
        self._detect_player()
    
    def _detect_player(self):
        """Detect available audio player"""
        if not self.enabled:
            return
        
        # Try winsound (Windows)
        try:
            import winsound
            self._player = 'winsound'
            logger.debug("Using winsound for audio playback")
            return
        except ImportError:
            pass
        
        # Try pygame
        try:
            import pygame
            pygame.mixer.init()
            self._player = 'pygame'
            logger.debug("Using pygame for audio playback")
            return
        except ImportError:
            pass
        
        # Try playsound
        try:
            import playsound
            self._player = 'playsound'
            logger.debug("Using playsound for audio playback")
            return
        except ImportError:
            pass
        
        # Try paplay (PulseAudio) or aplay (ALSA) on Linux
        try:
            result = subprocess.run(
                ['which', 'paplay'],
                capture_output=True,
                timeout=1
            )
            if result.returncode == 0:
                self._player = 'paplay'
                logger.debug("Using paplay for audio playback")
                return
        except Exception:
            pass
        
        try:
            result = subprocess.run(
                ['which', 'aplay'],
                capture_output=True,
                timeout=1
            )
            if result.returncode == 0:
                self._player = 'aplay'
                logger.debug("Using aplay for audio playback")
                return
        except Exception:
            pass
        
        logger.warning("No sound player available (winsound/pygame/playsound/paplay/aplay)")
        self.enabled = False
    
    def play(self, filepath: str, async_play: bool = True):
        """
        Play a sound file
        
        Args:
            filepath: Path to the sound file (can be relative or absolute)
            async_play: Whether to play asynchronously (non-blocking)
        """
        if not self.enabled or not self._player:
            return
        
        # Resolve path: if relative, resolve relative to base_path
        filepath_obj = Path(filepath)
        if not filepath_obj.is_absolute():
            filepath_obj = self.base_path / filepath_obj
        
        filepath = str(filepath_obj)
        
        # Check if file exists
        if not os.path.exists(filepath):
            logger.debug(f"Sound file not found: {filepath} (skipping)")
            return
        
        if async_play:
            # Play in background thread to avoid blocking
            thread = threading.Thread(
                target=self._play_sync,
                args=(filepath,),
                daemon=True
            )
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
            
            elif self._player == 'paplay':
                subprocess.run(
                    ['paplay', filepath],
                    capture_output=True,
                    timeout=5
                )
            
            elif self._player == 'aplay':
                subprocess.run(
                    ['aplay', '-q', filepath],
                    capture_output=True,
                    timeout=5
                )
            
            logger.debug(f"Played sound: {filepath}")
        
        except Exception as e:
            logger.error(f"Error playing sound {filepath}: {e}")
