# 👄 Whisper v2

A voice keyboard that transcribes Speech-to-Text (STT) for dictation.

| Version | Description |
|---------|-------------|
| [v2](https://github.com/mikesmullin/whisper/tree/v2) | Lightweight keyboard client; delegates STT to perception-voice server |
| [v1](https://github.com/mikesmullin/whisper/tree/v1) | Standalone voice keyboard with built-in Whisper AI model (GPU required) |

## ✨ Features

- **🎯 Voice-to-Keyboard**: Speaks directly into any application as typed text
- **🪶 Lightweight**: No GPU required; delegates STT to perception-voice server
- **⌨️ Configurable Commands**: Map spoken words to keyboard shortcuts
- **🔊 Audio Feedback**: Sound effects for listening state changes
- **📝 Word Mappings**: Convert spoken commands to actions (e.g., "new line" → newline)
- **🚫 Cancellation**: Press hotkey to discard pending transcription before it types

## 🎯 Use Cases

- **Accessibility**: Hands-free typing for users with mobility challenges
- **Productivity**: Dictate documents, emails, and messages
- **Content Creation**: Speed up writing workflows
- **Note-Taking**: Capture thoughts quickly during meetings or brainstorming

## 📋 Requirements

- Python 3.11+
- [perception-voice](https://github.com/mikesmullin/perception-voice) server
- Linux with X11 (for keyboard simulation)

## 🚀 Installation

Using `uv`:

```bash
uv tool install --editable .
```

## 🚀 Quick Start

### 1. Start perception-voice server

```bash
cd tmp/perception-voice
perception-voice serve
```

### 2. Start whisper

```bash
whisper
```

### 3. Use it

1. Press **Ctrl+Shift+Space** to start listening (you'll hear a sound)
2. Speak into your microphone
3. Watch the text appear in the active window
4. Press **Ctrl+Shift+Space** to stop listening

## 🚫 Cancellation

If you start speaking but change your mind:
- Press the hotkey **before** the transcription completes
- Any pending text will be discarded instead of typed

## ⚙️ Configuration

Edit `config.yaml` to customize:

```yaml
# Path to perception-voice socket
perception_voice:
  socket_path: "tmp/perception-voice/perception.sock"

# Hotkey to toggle listening
shortcuts:
  toggle_listening: "ctrl+shift+space"

# Exact-match command mappings
command_mappings:
  "work password": "~/wlogin.sh"

# Word mappings
word_mappings:
  "new line": "\n"
  "now undo": "ctrl+z"
  "now save": "ctrl+s"
  # ... see config.yaml for more
```

## 🔧 Systemd Integration

Install as a user service:

```bash
# Copy service file
cp whisper.service ~/.config/systemd/user/

# Edit paths in the service file
nano ~/.config/systemd/user/whisper.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable whisper
systemctl --user start whisper
```

**Note**: `whisper.service` depends on `perception-voice.service`. Make sure perception-voice is also set up as a systemd service.

## 📖 CLI Reference

```bash
whisper [-v] [-c CONFIG]
```

| Option | Description |
|--------|-------------|
| `-v, --verbose` | Enable verbose logging |
| `-c, --config FILE` | Path to config file (default: config.yaml) |

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  perception-voice serve                         │
│  (Runs Whisper AI model on GPU, transcribes audio)              │
│                         │                                       │
│               Unix Socket (IPC)                                 │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                       whisper v2                                 │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────────────────┐ │
│  │ Hotkey      │─▶│ Poll Server  │─▶│ Type to Keyboard      │ │
│  │ Listener    │   │ for Text     │   │ (with word mappings)  │ │
│  └─────────────┘   └──────────────┘   └───────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
               ┌─────────────────┐
               │ Active Window   │
               │ (VS Code, etc.) │
               └─────────────────┘
```

## 🙏 Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper) for speech recognition
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) for optimized inference
- [Silero VAD](https://github.com/snakers4/silero-vad) for voice activity detection
- [pynput](https://github.com/moses-palmer/pynput) for keyboard control
- [perception-voice](https://github.com/mikesmullin/perception-voice) for shared STT service