"""
Configuration management for whisper v2
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set

import yaml

logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "perception_voice": {
        "socket_path": "tmp/perception-voice/perception.sock",
    },
    "shortcuts": {
        "toggle_listening": "ctrl+shift+space",
    },
    "keyboard": {
        "typing_delay_ms": 20,
        "key_hold_ms": 20,
        "discard_phrases": [
            "thank you",
            "thanks",
            "you",
        ],
    },
    "word_mappings": {
        "new line": "\n",
        "insert bullet": "- ",
        "completion": "\t",
        "end of sentence": ".",
        "dot": ".",
        "comma": ",",
        "question mark": "?",
        "exclamation point": "!",
        "colon": ":",
        "semicolon": ";",
        "now undo": "ctrl+z",
        "now redo": "ctrl+y",
        "now copy": "ctrl+c",
        "now paste": "ctrl+v",
        "now cut": "ctrl+x",
        "now save": "ctrl+s",
    },
    "sounds": {
        "enabled": True,
        "on_listening_start": "sfx/on.wav",
        "on_listening_stop": "sfx/off.wav",
        "listening_state_delay_ms": 200,
    },
    "polling": {
        "interval_ms": 100,
    },
    "logging": {
        "timestamps": True,
        "verbose": False,
    },
}


class Config:
    """Configuration manager for whisper v2"""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration
        
        Args:
            config_path: Path to config file. If None, uses config.yaml in workspace root
        """
        if config_path is None:
            # Get workspace root (where this package is located)
            pkg_dir = Path(__file__).parent
            workspace_root = pkg_dir.parent
            config_path = workspace_root / "config.yaml"
        
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
                
                config = self._deep_merge(DEFAULT_CONFIG.copy(), user_config)
                logger.info(f"Loaded configuration from {self.config_path}")
                return config
            
            except Exception as e:
                logger.warning(f"Failed to load config from {self.config_path}: {e}")
                logger.warning("Using default configuration")
                return DEFAULT_CONFIG.copy()
        else:
            logger.info(f"Config file not found at {self.config_path}, using defaults")
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
            key: Key in dot notation (e.g., 'keyboard.typing_delay_ms')
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
    
    @property
    def socket_path(self) -> Path:
        """Get perception-voice socket path"""
        path_str = self.get('perception_voice.socket_path', 'perception.sock')
        path = Path(path_str)
        if not path.is_absolute():
            path = self.config_path.parent / path
        return path
    
    @property
    def toggle_listening_shortcut(self) -> str:
        """Get toggle listening hotkey"""
        return self.get('shortcuts.toggle_listening', 'ctrl+shift+space')
    
    @property
    def typing_delay_ms(self) -> int:
        """Get typing delay in milliseconds"""
        return self.get('keyboard.typing_delay_ms', 20)
    
    @property
    def key_hold_ms(self) -> int:
        """Get key hold time in milliseconds"""
        return self.get('keyboard.key_hold_ms', 20)
    
    @property
    def discard_phrases(self) -> Set[str]:
        """Get phrases to discard"""
        phrases = self.get('keyboard.discard_phrases', [])
        return {p.lower().strip() for p in phrases}
    
    @property
    def word_mappings(self) -> Dict[str, str]:
        """Get word to keystroke mappings"""
        return self.get('word_mappings', {})
    
    @property
    def sounds_enabled(self) -> bool:
        """Check if sounds are enabled"""
        return self.get('sounds.enabled', True)
    
    @property
    def sound_on_listening_start(self) -> str:
        """Get listening start sound file"""
        return self.get('sounds.on_listening_start', 'sfx/on.wav')
    
    @property
    def sound_on_listening_stop(self) -> str:
        """Get listening stop sound file"""
        return self.get('sounds.on_listening_stop', 'sfx/off.wav')
    
    @property
    def listening_state_delay_ms(self) -> int:
        """Get delay before state change takes effect"""
        return self.get('sounds.listening_state_delay_ms', 200)
    
    @property
    def polling_interval_ms(self) -> int:
        """Get polling interval in milliseconds"""
        return self.get('polling.interval_ms', 100)
    
    @property
    def timestamps_enabled(self) -> bool:
        """Check if timestamps are enabled in logging"""
        return self.get('logging.timestamps', True)
    
    @property
    def verbose_logging(self) -> bool:
        """Check if verbose logging is enabled"""
        return self.get('logging.verbose', False)
