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
# Clone the repository
git clone https://github.com/mikesmullin/whisper.git
cd whisper

# Install using uv
uv tool install --editable .
```

This installs the `whisper` command globally on your system with all required dependencies.

### Alternative Installation Methods

**Using pip:**
```bash
# Clone the repository
git clone https://github.com/mikesmullin/whisper.git
cd whisper

# Install with pip
pip install -e .
```

**For development (with all dependencies):**
```bash
pip install -e . -r requirements.txt
```

### macOS-Specific Setup

**CRITICAL**: On macOS, you **MUST** grant microphone and accessibility permissions or the app will not work:

#### Step 1: Grant Microphone Permission (Required)

Without this, the microphone will register zero audio.

1. Open **System Settings** (or System Preferences on older macOS)
2. Go to **Privacy & Security** → **Microphone**
3. Find and enable your terminal app (Terminal, iTerm2, etc.)
4. **Important**: You may need to **restart your terminal** after granting permission

#### Step 2: Grant Accessibility Permission (Required for keyboard typing & hotkeys)

Without this, whisper won't be able to type text or use global hotkeys.

1. Open **System Settings**
2. Go to **Privacy & Security** → **Accessibility**
3. Find your terminal application in the list (Terminal, iTerm2, Visual Studio Code, etc.)
4. **Enable** the checkbox next to it
5. **IMPORTANT**: Completely quit and restart your terminal (Cmd+Q, then relaunch)

#### Step 3: Test Installation

```bash
whisper --generate-config
whisper --headless --verbose
# Press Ctrl+Shift+Space to toggle listening
# Speak something
# Press Ctrl+C to quit
```

**Note**: If you encounter any dependency issues, all dependencies are automatically managed by `uv tool install` and run in an isolated environment.

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

### macOS-Specific Issues

**No Audio / Zero Transcriptions:**
- **Most common issue**: Microphone permissions not granted
- Go to System Settings → Privacy & Security → Microphone
- Enable your terminal application
- **Restart your terminal completely** after granting permission
- Test with the verification command in the setup section above

**Permission Denied (Microphone Access):**
- Go to System Settings → Privacy & Security → Microphone
- Grant permission to Terminal or your terminal application
- Restart the terminal and try again

**Global Hotkeys Not Working on macOS:**
- Grant Accessibility permissions to your terminal application:
  - Go to System Settings → Privacy & Security → Privacy → Accessibility
  - Add your terminal application to the list
- Try changing the hotkey combination in `~/.whisper.yaml`

**Installation Issues:**
- If you get dependency conflicts, try using a virtual environment:
  ```bash
  python -m venv whisper-env
  source whisper-env/bin/activate
  pip install -e .
  ```

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
