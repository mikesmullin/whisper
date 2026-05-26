"""
Sound playback for audio feedback
"""

import logging
import os
import subprocess
import time
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SoundPlayer:
    """
    Plays sound files for user feedback.

    Preferred backend is pygame.mixer: the audio device stays open for the
    lifetime of the process, sounds are pre-loaded into memory on first use,
    and playback goes directly into the SDL mixer thread — no subprocess
    fork/exec overhead per sound.  Falls back to paplay/aplay when pygame is
    not available.
    """

    def __init__(self, enabled: bool = True, base_path: Optional[Path] = None):
        self.enabled = enabled
        self.base_path = base_path or Path.cwd()
        self._cache: dict[str, object] = {}  # filepath -> pygame.mixer.Sound
        self._player: str | None = None
        self._init_player()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_player(self):
        if not self.enabled:
            return

        # pygame.mixer — keeps the audio device open; zero subprocess overhead
        try:
            import pygame.mixer as _mx
            _mx.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._player = 'pygame'
            logger.debug("SoundPlayer: using pygame.mixer")
            return
        except Exception as e:
            logger.debug(f"SoundPlayer: pygame.mixer unavailable ({e})")

        # winsound (Windows fallback)
        try:
            import winsound  # noqa: F401
            self._player = 'winsound'
            logger.debug("SoundPlayer: using winsound")
            return
        except ImportError:
            pass

        # paplay (PulseAudio) subprocess fallback
        try:
            if subprocess.run(['which', 'paplay'], capture_output=True, timeout=1).returncode == 0:
                self._player = 'paplay'
                logger.debug("SoundPlayer: using paplay (subprocess fallback)")
                return
        except Exception:
            pass

        # aplay (ALSA) subprocess fallback
        try:
            if subprocess.run(['which', 'aplay'], capture_output=True, timeout=1).returncode == 0:
                self._player = 'aplay'
                logger.debug("SoundPlayer: using aplay (subprocess fallback)")
                return
        except Exception:
            pass

        logger.warning("SoundPlayer: no audio backend available; sounds disabled")
        self.enabled = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play(self, filepath: str, async_play: bool = True):
        """Play a sound file.

        async_play=True  — fire and forget (returns immediately).
        async_play=False — block until playback is complete (use in worker threads).
        """
        if not self.enabled or not self._player:
            return

        path = Path(filepath)
        if not path.is_absolute():
            path = self.base_path / path

        if not path.exists():
            logger.debug(f"SoundPlayer: file not found: {path}")
            return

        if async_play:
            threading.Thread(target=self._play_sync, args=(path,), daemon=True).start()
        else:
            self._play_sync(path)

    # ------------------------------------------------------------------
    # Internal playback
    # ------------------------------------------------------------------

    def _load_pygame(self, path: Path):
        """Return a cached pygame.mixer.Sound, loading on first use."""
        key = str(path)
        if key not in self._cache:
            import pygame.mixer as _mx
            self._cache[key] = _mx.Sound(str(path))
        return self._cache[key]

    def _play_sync(self, path: Path):
        try:
            if self._player == 'pygame':
                sound = self._load_pygame(path)
                channel = sound.play()
                # Wait for this channel to finish so async_play=False is truly blocking
                if channel is not None:
                    while channel.get_busy():
                        time.sleep(0.001)

            elif self._player == 'winsound':
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME)

            elif self._player == 'paplay':
                subprocess.run(['paplay', str(path)], capture_output=True, timeout=5)

            elif self._player == 'aplay':
                subprocess.run(['aplay', '-q', str(path)], capture_output=True, timeout=5)

        except Exception as e:
            logger.error(f"SoundPlayer: error playing {path}: {e}")
