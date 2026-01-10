# 👄 Whisper

A cross-platform voice keyboard that transcribes your speech into typed text in real-time. Speak naturally and watch your words appear on screen!

## ✨ Features

- **🎯 Voice-to-Keyboard**: Speaks directly into any application as typed text
- **🔄 Cross-Platform**: Works on Windows, macOS, and Linux
- **⚡ Real-Time Preview**: See words appear instantly as you speak with dual-model transcription
- **🎯 Accurate Final Text**: Large model refines transcription after you finish speaking
- **🔇 Dual-VAD System**: WebRTC + Silero for fast and accurate speech detection
- **⌨️ Configurable Commands**: Map spoken words to keyboard shortcuts
- **� Audio Feedback**: Sound effects for listening state changes
- **📝 Word Mappings**: Convert spoken commands to actions (e.g., "new line" → newline)
- **📊 Performance Monitoring**: Timestamped logging to measure latency

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
uv tool install --editable . --with webrtcvad-wheels --with scipy
```

This installs the `whisper` command globally on your system with all required dependencies in an isolated environment.

### macOS-Specific Setup

**CRITICAL**: On macOS, you **MUST** grant microphone and accessibility permissions or the app will not work:

#### Step 1: Grant Microphone Permission (Required)

Without this, the microphone will register zero audio.

1. Open **System Settings** (or System Preferences on older macOS)
2. Go to **Privacy & Security** → **Microphone**
3. Find and enable your terminal app (Terminal, iTerm2, etc.)
4. **Important**: You may need to **restart your terminal** after granting permission

#### Step 2: Grant Accessibility Permission (Required for keyboard typing)

Without this, whisper won't be able to type text.

1. Open **System Settings**
2. Go to **Privacy & Security** → **Accessibility**
3. Find your terminal application in the list (Terminal, iTerm2, Visual Studio Code, etc.)
4. **Enable** the checkbox next to it
5. **IMPORTANT**: Completely quit and restart your terminal (Cmd+Q, then relaunch)

#### Step 3: Install macOS-specific dependencies

```bash
pip install pyobjc-framework-Cocoa
```

#### Step 4: Test Installation

```bash
whisper --verbose
# Press Ctrl+Shift+Space to start listening
# Speak something
# Press Ctrl+Shift+Space to stop listening
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

### 🎮 Controls

Once running:

1. **Toggle Listening**: Press **Ctrl+Shift+Space** to start/stop (default hotkey, configurable in `config.yaml`)
2. **Switch Mode**: Double-press **Ctrl+Shift+Space** (2x within 1 second) to rotate between LISTEN and AGENT modes
3. **Exit**: Press `Ctrl+C`

### 🎭 Modes

Whisper supports two listening modes:

#### LISTEN Mode (Default)
- Transcribes speech directly to keyboard input
- Words appear in the active application as you speak
- Use for dictation, writing, coding, etc.

#### AGENT Mode
- Transcribes speech to a shell command instead of keyboard
- Text is buffered until silence timeout (default 0.5 seconds)
- First word becomes `$AGENT` (normalized: lowercase, punctuation stripped)
- Remaining words become `$PROMPT`
- Then executes a configurable shell command with both variables
- Shell output is passed through to stdout for visibility
- Perfect for voice-controlled AI assistants with multiple targets/agents

**Example use case**: Say "ada what is the weather" to route to different AI agents:
```yaml
agent:
  command_template: 'subd -t "$AGENT" "$PROMPT"'
  buffer_timeout: 0.5
```
This executes: `subd -t "ada" "what is the weather"`

### 🎙️ How It Works

1. **Press Ctrl+Shift+Space** → Listening starts
2. **Start speaking** → See words appear in real-time as you speak (preview mode)
3. **Stop speaking** → After brief pause (~0.6s), preview is replaced with accurate final transcription
4. **Press Ctrl+Shift+Space** → Listening stops

**Performance**: 
- Preview appears in ~300ms (instant feedback!)
- Final transcription in ~600ms after speech ends
- Total: ~2-3x faster than traditional speech-to-text

### ⚙️ Configuration

Whisper uses a YAML configuration file at `config.yaml` in the workspace root. On first run, if `config.yaml` doesn't exist, it will be automatically created from `config.example.yaml`. You can customize it by copying the example:

```bash
cp config.example.yaml config.yaml
```

#### Customizing Word Mappings

Edit `config.yaml` to add your own voice commands:

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
  
  # Hotkeys (execute keyboard shortcuts)
  now save: "ctrl+s"
  now undo: "ctrl+z"
  now copy: "ctrl+c"
  
  # Custom shortcuts
  my email: "your.email@example.com"
  my address: "123 Main St, City, State"
```

#### Performance Tuning

**For faster response:**
```yaml
vad:
  silero_sensitivity: 0.02  # More sensitive
audio:
  post_speech_silence_duration: 0.4  # Faster finalization
```

**For better accuracy:**
```yaml
transcription:
  model: "large-v3"  # Most accurate
  beam_size: 7  # Higher quality
```

**For lower resource usage:**
```yaml
transcription:
  model: "medium"  # Faster than large-v2
  realtime_model: "tiny"  # Minimal overhead
```

#### Agent Mode Configuration

Configure the AGENT mode for voice-controlled shell commands:

```yaml
agent:
  # Enable/disable agent mode (double-tap to activate)
  enabled: true
  
  # Shell command template with variables:
  #   $AGENT - First word (lowercase, punctuation stripped)
  #   $PROMPT - Remaining words
  # Example: "Ada, tell me a joke" → $AGENT="ada", $PROMPT="tell me a joke"
  command_template: 'subd -t "$AGENT" "$PROMPT"'
  
  # Seconds of silence before sending buffered text to command
  buffer_timeout: 0.5
  
  # Seconds within which double-press is detected
  double_tap_window: 0.5
```

**How Agent Mode works:**
1. Double-press the hotkey to switch to AGENT mode
2. Speak your command - text is buffered (e.g., "Home, turn on the lights")
3. After silence timeout, the first word becomes `$AGENT` ("home") and the rest becomes `$PROMPT` ("turn on the lights")
4. Command executes with both variables substituted
5. Command output streams to stdout in real-time
6. Double-press again to switch back to LISTEN mode
7. If you switch modes or stop listening before the buffer timeout, the buffered text is discarded

### 🔧 Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `-c, --config FILE` | Configuration file path | `config.yaml` |
| `-v, --verbose` | Show transcriptions in console | Off |
| `-h, --help` | Show help message | - |

### 🎤 Microphone Setup

Configure your system's default microphone:

**Linux (PulseAudio/PipeWire):**
```bash
# List available sources
pactl list sources short

# Set default microphone
pactl set-default-source <source-name>
```

**Windows/macOS:**
Set your default microphone in system sound settings.

The application will automatically use your system's default microphone.

## 🔍 How It Works

1. **Voice Activity Detection (VAD)**: Uses Silero VAD to detect when you're speaking
2. **Audio Buffering**: Collects audio until silence is detected
3. **Transcription**: Processes audio through Whisper (tiny model for speed)
4. **Word Mapping**: Applies configured word-to-keystroke mappings
5. **Keyboard Output**: Types transcribed text using `pynput`

## 🐛 Troubleshooting

### Microphone Not Detected
- Check microphone permissions in system settings
- Verify your system's default microphone is set correctly
- Test microphone with other applications to ensure it works

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
- Try changing the hotkey in `config.yaml`
- Run with `sudo` on Linux if needed for global hotkey access

### Transcription Quality Issues
- Speak clearly and at a moderate pace
- Reduce background noise
- Adjust `min_utterance_duration` in config
- Consider upgrading to a larger Whisper model (edit config file)

## 🎨 Customization

### Using a Different Whisper Model

Edit `config.yaml` and change the model size:

```yaml
transcription:
  model: "base"  # Options: tiny, base, small, medium, large-v2, large-v3
  device: "cpu"  # or "cuda" for GPU
  compute_type: "int8"  # int8, float16, float32
```

Larger models are more accurate but slower.

### Different Languages

Edit `config.yaml` and change the language parameter:

```yaml
transcription:
  language: "es"  # Spanish, French (fr), German (de), etc.
```

## 🙏 Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper) for speech recognition
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) for optimized inference
- [Silero VAD](https://github.com/snakers4/silero-vad) for voice activity detection
- [pynput](https://github.com/moses-palmer/pynput) for keyboard control
