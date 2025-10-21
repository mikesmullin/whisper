"""
System tray integration for Whisper voice keyboard
"""

import logging
import threading
from typing import Callable, Optional
from pathlib import Path
import io

try:
    from PIL import Image, ImageDraw
    import pystray
    from pystray import MenuItem as item
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    logging.warning("System tray dependencies not available. Install pystray and pillow.")

logger = logging.getLogger(__name__)


def create_icon_image(color: str = "green", size: int = 64) -> Optional['Image.Image']:
    """
    Create a simple icon image
    
    Args:
        color: Icon color ('green' for inactive, 'red' for active)
        size: Icon size in pixels
        
    Returns:
        PIL Image object
    """
    if not TRAY_AVAILABLE:
        return None
    
    # Create a simple colored circle
    image = Image.new('RGB', (size, size), 'white')
    draw = ImageDraw.Draw(image)
    
    # Draw a colored circle
    padding = size // 8
    draw.ellipse(
        [padding, padding, size - padding, size - padding],
        fill=color,
        outline='black',
        width=2
    )
    
    # Add a microphone symbol (simple lines)
    center_x = size // 2
    center_y = size // 2
    mic_height = size // 4
    
    # Mic body (vertical line)
    draw.line(
        [(center_x, center_y - mic_height // 2), (center_x, center_y + mic_height // 2)],
        fill='white',
        width=3
    )
    
    # Mic base (horizontal line)
    draw.line(
        [(center_x - mic_height // 3, center_y + mic_height // 2),
         (center_x + mic_height // 3, center_y + mic_height // 2)],
        fill='white',
        width=3
    )
    
    return image


class SystemTray:
    """System tray icon and menu for Whisper voice keyboard"""
    
    def __init__(
        self,
        on_toggle: Optional[Callable] = None,
        on_quit: Optional[Callable] = None,
        notifications_enabled: bool = True
    ):
        """
        Initialize system tray
        
        Args:
            on_toggle: Callback when toggle menu item is clicked
            on_quit: Callback when quit menu item is clicked
            notifications_enabled: Whether to show notifications
        """
        if not TRAY_AVAILABLE:
            logger.warning("System tray not available")
            self.icon = None
            return
        
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.notifications_enabled = notifications_enabled
        self.is_listening = False
        
        # Create icons
        self.inactive_icon = create_icon_image("green")
        self.active_icon = create_icon_image("red")
        
        # Create tray icon
        self.icon = pystray.Icon(
            "whisper",
            self.inactive_icon,
            "Whisper Voice Keyboard",
            menu=pystray.Menu(
                item('Toggle Listening', self._on_toggle_click),
                item('Quit', self._on_quit_click)
            )
        )
        
        logger.info("System tray initialized")
    
    def _on_toggle_click(self, icon, item):
        """Handle toggle menu click"""
        if self.on_toggle:
            self.on_toggle()
    
    def _on_quit_click(self, icon, item):
        """Handle quit menu click"""
        if self.icon:
            self.icon.stop()
        if self.on_quit:
            self.on_quit()
    
    def run(self):
        """Run the system tray (blocking)"""
        if self.icon:
            self.icon.run()
    
    def run_detached(self):
        """Run the system tray in a separate thread"""
        if self.icon:
            thread = threading.Thread(target=self.icon.run, daemon=True)
            thread.start()
            logger.info("System tray running in background")
    
    def stop(self):
        """Stop the system tray"""
        if self.icon:
            self.icon.stop()
            logger.info("System tray stopped")
    
    def set_listening(self, is_listening: bool):
        """
        Update icon to reflect listening state
        
        Args:
            is_listening: Whether currently listening
        """
        if not self.icon:
            return
        
        self.is_listening = is_listening
        
        # Update icon
        if is_listening:
            self.icon.icon = self.active_icon
            self.icon.title = "Whisper Voice Keyboard (Listening)"
        else:
            self.icon.icon = self.inactive_icon
            self.icon.title = "Whisper Voice Keyboard (Idle)"
        
        logger.debug(f"Tray icon updated: listening={is_listening}")
    
    def notify(self, title: str, message: str):
        """
        Show a notification
        
        Args:
            title: Notification title
            message: Notification message
        """
        if not self.icon or not self.notifications_enabled:
            return
        
        try:
            self.icon.notify(message, title)
            logger.debug(f"Notification: {title}: {message}")
        except Exception as e:
            logger.error(f"Failed to show notification: {e}")
    
    def update_menu(self, is_listening: bool):
        """
        Update menu items based on state
        
        Args:
            is_listening: Whether currently listening
        """
        if not self.icon:
            return
        
        # Update menu
        self.icon.menu = pystray.Menu(
            item(
                'Stop Listening' if is_listening else 'Start Listening',
                self._on_toggle_click
            ),
            item('Quit', self._on_quit_click)
        )
