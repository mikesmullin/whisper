"""
Configuration management for Whisper voice keyboard
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import yaml

logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "audio": {
        "sample_rate": 16000,
        "mic_device": None,  # Auto-detect if None
        "min_utterance_duration": 0.8,  # seconds
        "silence_chunks": 15,
    },
    "shortcuts": {
        "toggle_on": "ctrl+shift+space",
        "toggle_off": "ctrl+shift+space",  # Same key toggles on/off
    },
    "word_mappings": {
        "new line": "\n",
        "insert bullet": "- ",
        "tab complete": "\t",
        "end of sentence": ".",
        "dot": ".",
        "comma": ",",
        "question mark": "?",
        "exclamation point": "!",
        "colon": ":",
        "semicolon": ";",
        # Hotkeys (will be executed as keyboard shortcuts)
        "now undo": "ctrl+z",
        "now redo": "ctrl+y",
        "now copy": "ctrl+c",
        "now paste": "ctrl+v",
        "now cut": "ctrl+x",
        "now save": "ctrl+s",
    },
    "notifications": {
        "enabled": True,
        "show_on_start": True,
        "show_on_toggle": True,
    },
    "system_tray": {
        "enabled": True,
    },
}


class Config:
    """Configuration manager for Whisper voice keyboard"""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration
        
        Args:
            config_path: Path to config file. If None, uses ~/.whisper.yaml
        """
        if config_path is None:
            config_path = Path.home() / ".whisper.yaml"
        
        self.config_path = config_path
        self.config = self._load_config()
        
        logger.info(f"Configuration loaded from {self.config_path}")
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file or use defaults"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_config = yaml.safe_load(f)
                
                if user_config is None:
                    user_config = {}
                
                # Merge with defaults (user config overrides defaults)
                config = self._deep_merge(DEFAULT_CONFIG.copy(), user_config)
                logger.info(f"Loaded configuration from {self.config_path}")
                return config
            
            except Exception as e:
                logger.warning(f"Failed to load config from {self.config_path}: {e}")
                logger.warning("Using default configuration")
                return DEFAULT_CONFIG.copy()
        else:
            logger.info(f"Config file not found at {self.config_path}, using defaults")
            logger.info(f"Create {self.config_path} to customize settings")
            return DEFAULT_CONFIG.copy()
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries"""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation key
        
        Args:
            key: Key in dot notation (e.g., 'audio.sample_rate')
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def save_default_config(self):
        """Save default configuration to file"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
            
            logger.info(f"Saved default configuration to {self.config_path}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to save config to {self.config_path}: {e}")
            return False
    
    @property
    def word_mappings(self) -> Dict[str, str]:
        """Get word to keystroke mappings"""
        return self.get('word_mappings', {})
    
    @property
    def sample_rate(self) -> int:
        """Get audio sample rate"""
        return self.get('audio.sample_rate', 16000)
    
    @property
    def mic_device(self) -> Optional[int]:
        """Get microphone device index"""
        return self.get('audio.mic_device')
    
    @property
    def min_utterance_duration(self) -> float:
        """Get minimum utterance duration in seconds"""
        return self.get('audio.min_utterance_duration', 1.5)
    
    @property
    def silence_chunks(self) -> int:
        """Get number of silence chunks before ending utterance"""
        return self.get('audio.silence_chunks', 15)
    
    @property
    def toggle_on_shortcut(self) -> str:
        """Get keyboard shortcut to toggle listening on"""
        return self.get('shortcuts.toggle_on', 'ctrl+shift+space')
    
    @property
    def toggle_off_shortcut(self) -> str:
        """Get keyboard shortcut to toggle listening off"""
        return self.get('shortcuts.toggle_off', 'ctrl+shift+space')
    
    @property
    def notifications_enabled(self) -> bool:
        """Check if notifications are enabled"""
        return self.get('notifications.enabled', True)
    
    @property
    def system_tray_enabled(self) -> bool:
        """Check if system tray is enabled"""
        return self.get('system_tray.enabled', True)
