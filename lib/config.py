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
        "mic_device": None,  # Auto-detect if None, or use device ID (int)
        "buffer_size": 512,  # Silero requires >=512, WebRTC uses first 480
        "min_utterance_duration": 1.1,  # Minimum speech duration (seconds)
        "post_speech_silence_duration": 0.6,  # Silence before finalizing (seconds)
        "pre_recording_buffer_duration": 1.0,  # Buffer before speech starts (seconds)
    },
    "transcription": {
        # Main model (final accurate transcription)
        "model": "large-v3",  # Options: tiny, base, small, medium, large-v2, large-v3
        "device": "cuda",  # "auto", "cpu", or "cuda" - cuda for GPU acceleration
        "compute_type": "float16",  # "auto", "int8", "float16", "float32" - float16 for GPU
        "beam_size": 5,
        "language": "en",  # Language code or None for auto-detect
        
        # Realtime preview model
        "realtime_model": "tiny.en",
        "beam_size_realtime": 3,
        "enable_realtime_transcription": True,
        "realtime_processing_pause": 0.02,  # Seconds between realtime updates
        "type_realtime_preview": False,  # Type preview to keyboard (causes backspace corrections)
    },
    "vad": {
        # WebRTC (fast filter)
        "webrtc_sensitivity": 3,  # 0-3, higher = less sensitive to noise
        
        # Silero (accurate verification)
        "silero_sensitivity": 0.05,  # 0.0-1.0, lower = more sensitive
        "silero_use_onnx": True,  # Use ONNX for faster CPU inference
    },
    "shortcuts": {
        "toggle_listening": "ctrl+shift+space",  # Hotkey to toggle listening (e.g., "ctrl+shift+space", "ctrl+alt+l")
    },
    "agent": {
        "enabled": True,  # Enable agent mode (double-tap hotkey to activate)
        "command_template": 'subd -t ada "$PROMPT"',  # Shell command template ($PROMPT replaced with transcription)
        "buffer_timeout": 2.0,  # Seconds of silence before sending buffered text to command
        "double_tap_window": 0.5,  # Seconds within which a second tap counts as double-tap
    },
    "keyboard": {
        "typing_delay_ms": 20,  # Milliseconds delay between each keystroke (prevents skipping in some form input contexts)
        "key_hold_ms": 20,  # Milliseconds to hold key down before release (for SDL2/game input compatibility)
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
        # Hotkeys (will be executed as keyboard shortcuts)
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
        "on_agent_mode": "sfx/agent.wav",
        "listening_state_delay_ms": 500,
    },
    "logging": {
        "timestamps": True,  # Add timestamps to log output
        "verbose": False,
    },
}


class Config:
    """Configuration manager for Whisper voice keyboard"""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration
        
        Args:
            config_path: Path to config file. If None, uses config.yaml in workspace root
        """
        if config_path is None:
            # Get the directory where this config.py file is located
            lib_dir = Path(__file__).parent
            # Get workspace root (parent of lib/)
            workspace_root = lib_dir.parent
            # Use config.yaml in workspace root
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
    def buffer_size(self) -> int:
        """Get audio buffer size"""
        return self.get('audio.buffer_size', 512)
    
    @property
    def mic_device(self):
        """Get microphone device (can be int ID or str name)"""
        return self.get('audio.mic_device')
    
    @property
    def min_utterance_duration(self) -> float:
        """Get minimum utterance duration in seconds"""
        return self.get('audio.min_utterance_duration', 1.1)
    
    @property
    def post_speech_silence_duration(self) -> float:
        """Get post-speech silence duration in seconds"""
        return self.get('audio.post_speech_silence_duration', 0.6)
    
    @property
    def pre_recording_buffer_duration(self) -> float:
        """Get pre-recording buffer duration in seconds"""
        return self.get('audio.pre_recording_buffer_duration', 1.0)
    
    # Transcription properties
    @property
    def model(self) -> str:
        """Get main transcription model"""
        return self.get('transcription.model', 'large-v2')
    
    @property
    def realtime_model(self) -> str:
        """Get realtime preview model"""
        return self.get('transcription.realtime_model', 'tiny.en')
    
    @property
    def device(self) -> str:
        """Get compute device (cpu or cuda)"""
        return self.get('transcription.device', 'cpu')
    
    @property
    def compute_type(self) -> str:
        """Get compute type (int8, float16, float32)"""
        return self.get('transcription.compute_type', 'int8')
    
    @property
    def beam_size(self) -> int:
        """Get beam size for main model"""
        return self.get('transcription.beam_size', 5)
    
    @property
    def beam_size_realtime(self) -> int:
        """Get beam size for realtime model"""
        return self.get('transcription.beam_size_realtime', 3)
    
    @property
    def language(self) -> str:
        """Get language code"""
        return self.get('transcription.language', 'en')
    
    @property
    def enable_realtime_transcription(self) -> bool:
        """Check if realtime transcription is enabled"""
        return self.get('transcription.enable_realtime_transcription', True)
    
    @property
    def realtime_processing_pause(self) -> float:
        """Get realtime processing pause in seconds"""
        return self.get('transcription.realtime_processing_pause', 0.02)
    
    # VAD properties
    @property
    def webrtc_sensitivity(self) -> int:
        """Get WebRTC VAD sensitivity (0-3)"""
        return self.get('vad.webrtc_sensitivity', 3)
    
    @property
    def silero_sensitivity(self) -> float:
        """Get Silero VAD sensitivity (0.0-1.0)"""
        return self.get('vad.silero_sensitivity', 0.05)
    
    @property
    def silero_use_onnx(self) -> bool:
        """Check if ONNX should be used for Silero"""
        return self.get('vad.silero_use_onnx', True)
    
    # Shortcuts
    @property
    def toggle_listening_shortcut(self) -> str:
        """Get keyboard shortcut to toggle listening"""
        return self.get('shortcuts.toggle_listening', 'ctrl+shift+space')
    
    @property
    def silence_chunks(self) -> int:
        """Get number of silence chunks before ending utterance (legacy support)"""
        # Calculate from post_speech_silence_duration for backward compatibility
        duration = self.post_speech_silence_duration
        return int((self.sample_rate / self.buffer_size) * duration)
    
    @property
    def toggle_on_shortcut(self) -> str:
        """Get keyboard shortcut to toggle listening on (legacy support)"""
        return self.toggle_listening_shortcut
    
    @property
    def toggle_off_shortcut(self) -> str:
        """Get keyboard shortcut to toggle listening off (legacy support)"""
        return self.toggle_listening_shortcut
    
    @property
    def timestamps_enabled(self) -> bool:
        """Check if timestamps are enabled in logging"""
        return self.get('logging.timestamps', True)
    
    @property
    def verbose_logging(self) -> bool:
        """Check if verbose logging is enabled"""
        return self.get('logging.verbose', False)
    
    @property
    def type_realtime_preview(self) -> bool:
        """Check if realtime preview should be typed to keyboard"""
        return self.get('transcription.type_realtime_preview', False)
    
    @property
    def typing_delay_ms(self) -> int:
        """Get typing delay in milliseconds between keystrokes"""
        return self.get('keyboard.typing_delay_ms', 10)
    
    @property
    def key_hold_ms(self) -> int:
        """Get key hold duration in milliseconds (time between press and release)"""
        return self.get('keyboard.key_hold_ms', 20)
    
    @property
    def sounds_enabled(self) -> bool:
        """Check if sound playback is enabled"""
        return self.get('sounds.enabled', True)
    
    @property
    def sound_on_listening_start(self) -> str:
        """Get sound file path for listening start"""
        return self.get('sounds.on_listening_start', 'sfx/on.wav')
    
    @property
    def sound_on_listening_stop(self) -> str:
        """Get sound file path for listening stop"""
        return self.get('sounds.on_listening_stop', 'sfx/off.wav')

    # Agent mode properties
    @property
    def agent_enabled(self) -> bool:
        """Check if agent mode is enabled"""
        return self.get('agent.enabled', True)

    @property
    def agent_command_template(self) -> str:
        """Get agent mode shell command template"""
        return self.get('agent.command_template', 'subd -t ada "$PROMPT"')

    @property
    def agent_buffer_timeout(self) -> float:
        """Get agent mode buffer timeout in seconds"""
        return self.get('agent.buffer_timeout', 2.0)

    @property
    def agent_double_tap_window(self) -> float:
        """Get double-tap detection window in seconds"""
        return self.get('agent.double_tap_window', 1.0)

    @property
    def sound_on_agent_mode(self) -> str:
        """Get sound file path for agent mode activation"""
        return self.get('sounds.on_agent_mode', 'sfx/agent.wav')

    @property
    def listening_state_delay_ms(self) -> int:
        """Get delay in ms before audio resumes/pauses after listening state changes"""
        return self.get('sounds.listening_state_delay_ms', 500)
