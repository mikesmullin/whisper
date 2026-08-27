"""X11 NumLock latch: read the lock *level*, not press/release events."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class NumLockMonitor:
    """Query whether NumLock is currently on (X modifier / LED state)."""

    def __init__(self) -> None:
        self._display = None
        self._root = None
        self._mask = 0
        self._warned = False

    def is_on(self) -> bool | None:
        """Return True if NumLock is on, False if off, or None if unreadable."""
        try:
            self._ensure()
            if not self._mask:
                if not self._warned:
                    logger.warning("NumLock is not mapped as an X modifier; latch disabled")
                    self._warned = True
                return None
            return bool(self._root.query_pointer().mask & self._mask)
        except Exception as e:
            if not self._warned:
                logger.warning(f"Cannot read NumLock state: {e}")
                self._warned = True
            return None

    def close(self) -> None:
        if self._display is None:
            return
        try:
            self._display.close()
        except Exception:
            pass
        self._display = None
        self._root = None

    def _ensure(self) -> None:
        if self._display is not None:
            return
        from Xlib import display
        from pynput._util.xorg import numlock_mask

        self._display = display.Display()
        self._root = self._display.screen().root
        self._mask = numlock_mask(self._display)
        logger.debug(f"NumLock X modifier mask: {self._mask:#x}")
