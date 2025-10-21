# 👄 Whisper

A cross-platform voice keyboard that transcribes your speech into typed text in real-time. Speak naturally and watch your words appear on screen!

## ✨ Features

- **🎯 Voice-to-Keyboard**: Speaks directly into any application as typed text
- **🔄 Cross-Platform**: Works on Windows, macOS, and Linux
- **⚡ Real-Time**: Fast transcription with <1s latency using Whisper
- **🔇 Smart VAD**: Intelligent voice activity detection to filter silence
- **⌨️ Configurable Commands**: Map spoken words to keyboard shortcuts
- **🔔 System Tray Integration**: Background operation with notifications
- **🔥 Hotkey Control**: Toggle listening on/off with keyboard shortcuts
- **📝 Word Mappings**: Convert spoken commands to actions (e.g., "bullet" → newline + bullet)

## 🎯 Use Cases

- **Accessibility**: Hands-free typing for users with mobility challenges
- **Productivity**: Dictate documents, emails, and messages
- **Content Creation**: Speed up writing workflows
- **Note-Taking**: Capture thoughts quickly during meetings or brainstorming

## 📋 Requirements

- Python 3.11+
- ~500MB disk space for models (downloaded automatically on first run)
- Microphone

## 🚀 Installation

### Quick Install (Recommended)

Using `uv` (fast Python package installer):

```bash
uv tool install --editable . --with pynput --with pystray --with pillow --with pyyaml --with numpy --with torch --with torchaudio --with sounddevice --with faster-whisper
```

This installs the `whisper` command globally on your system.

## 📖 Usage

### Basic Usage

**Run with default settings:**
```bash
whisper
```

**Run in verbose mode (see transcriptions):**
```bash
whisper --verbose
```

**Run without system tray (headless):**
```bash
whisper --headless
```

**Generate default configuration file:**
```bash
whisper --generate-config
```

### 🎮 Controls

Once running:

1. **Toggle Listening**: Press `Ctrl+Shift+Space` (configurable)
2. **System Tray**: Right-click the tray icon for menu
   - Start/Stop Listening
   - Quit
3. **Exit**: Press `Ctrl+C` or use tray menu

### ⚙️ Configuration

Whisper uses a YAML configuration file at `~/.whisper.yaml`. Generate it with:

```bash
whisper --generate-config
```

#### Default Configuration

```yaml
audio:
  sample_rate: 16000
  mic_device: null  # Auto-detect
  min_utterance_duration: 1.5  # seconds
  silence_chunks: 15

shortcuts:
  toggle_on: "ctrl+shift+space"
  toggle_off: "ctrl+shift+space"

word_mappings:
  ENTER: "\n"
  enter: "\n"
  new line: "\n"
  bullet: "\n - "
  bullet point: "\n - "
  tab: "\t"
  TAB: "\t"

notifications:
  enabled: true
  show_on_start: true
  show_on_toggle: true

system_tray:
  enabled: true
```

#### Customizing Word Mappings

Edit `~/.whisper.yaml` to add your own voice commands:

```yaml
word_mappings:
  # Punctuation
  period: "."
  comma: ","
  question mark: "?"
  
  # Formatting
  new paragraph: "\n\n"
  indent: "    "
  
  # Code
  code block: "\n```\n"
  arrow: " -> "
  equals: " = "
  
  # Custom shortcuts
  my email: "your.email@example.com"
  my address: "123 Main St, City, State"
```

### 🔧 Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `-m, --mic N` | Microphone device index | Auto-detect |
| `-c, --config FILE` | Configuration file path | `~/.whisper.yaml` |
| `-v, --verbose` | Show transcriptions in console | Off |
| `--headless` | Run without system tray | Off |
| `--generate-config` | Create default config and exit | - |
| `-h, --help` | Show help message | - |

### 🎤 Finding Your Microphone Device

If auto-detection doesn't work, find your device ID:

```python
import sounddevice as sd
print(sd.query_devices())
```

Then use it:
```bash
whisper --mic 1
```

## 🔍 How It Works

1. **Voice Activity Detection (VAD)**: Uses Silero VAD to detect when you're speaking
2. **Audio Buffering**: Collects audio until silence is detected
3. **Transcription**: Processes audio through Whisper (tiny model for speed)
4. **Word Mapping**: Applies configured word-to-keystroke mappings
5. **Keyboard Output**: Types transcribed text using `pynput`

## 🐛 Troubleshooting

### Microphone Not Detected
- Check microphone permissions in system settings
- Try specifying device ID with `--mic N`
- List devices: `python -c "import sounddevice; print(sounddevice.query_devices())"`

### Hotkeys Not Working
- Some desktop environments may conflict with global hotkeys
- Try changing the hotkey in `~/.whisper.yaml`
- Run with `sudo` on Linux if needed for global hotkey access

### System Tray Icon Not Showing
- Install required dependencies: `pip install pystray pillow`
- Run in headless mode: `whisper --headless`
- Check desktop environment compatibility

### Transcription Quality Issues
- Speak clearly and at a moderate pace
- Reduce background noise
- Adjust `min_utterance_duration` in config
- Consider upgrading to a larger Whisper model (edit `whisper.py`)

## 🎨 Customization

### Using a Different Whisper Model

Edit `whisper.py` and change the model size:

```python
# Options: tiny, base, small, medium, large
self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
```

Larger models are more accurate but slower.

### Adding Custom Notifications

Modify `lib/tray.py` to customize notification behavior.

### Different Languages

Edit `whisper.py` and change the language parameter:

```python
segments, info = self.whisper_model.transcribe(
    audio,
    language="es",  # Spanish, French (fr), German (de), etc.
    beam_size=5
)
```

## 🙏 Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper) for speech recognition
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) for optimized inference
- [Silero VAD](https://github.com/snakers4/silero-vad) for voice activity detection
- [pynput](https://github.com/moses-palmer/pynput) for keyboard control
- [pystray](https://github.com/moses-palmer/pystray) for system tray integration
