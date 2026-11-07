# 👄 Whisper v3

A voice keyboard that transcribes Speech-to-Text (STT) for dictation.

| Version | Description |
|---------|-------------|
| [v3](https://github.com/mikesmullin/whisper/tree/v3) | Rust keyboard client; single binary, no runtime deps |
| [v2](https://github.com/mikesmullin/whisper/tree/v2) | Python keyboard client; delegates STT to perception-voice server |
| [v1](https://github.com/mikesmullin/whisper/tree/v1) | Standalone voice keyboard with built-in Whisper AI model (GPU required) |

## ✨ Features

- **🎯 Voice-to-Keyboard**: Speaks directly into any application as typed text
- **🪶 Lightweight**: No GPU required; delegates STT to perception-voice server
- **⚡ Instant start**: One static binary, no interpreter in the dictation path
- **⌨️ Configurable Commands**: Map spoken words to keyboard shortcuts
- **🐚 Shell Commands**: Spoken phrases run scripts, with `*` wildcards and `$WORDS` capture
- **🗣️ Activation Keywords**: Hands-free `"work activate"` / `"work deactivate"`, heard even while listening is off
- **🔢 NumLock Latch**: A persistent listening mode, as an alternative to push-to-talk
- **📋 Clipboard Paste**: For text that has to arrive all at once
- **🔊 Audio Feedback**: Sound effects for listening state changes
- **📝 Word Mappings**: Convert spoken commands to actions (e.g., "new line" → newline)
- **🚫 Cancellation**: Press hotkey to discard pending transcription before it types

## 🎯 Use Cases

- **Accessibility**: Hands-free typing for users with mobility challenges
- **Productivity**: Dictate documents, emails, and messages
- **Content Creation**: Speed up writing workflows
- **Note-Taking**: Capture thoughts quickly during meetings or brainstorming

## 📋 Requirements

- Rust toolchain (edition 2021)
- [perception-voice](https://github.com/mikesmullin/perception-voice) server
- Linux with X11 (for keyboard simulation). Wayland is not supported —
  XTEST and key grabs are X11-only.
- `xclip`, for clipboard-paste mode and the `{{clipboard}}` placeholder

## 🚀 Installation

```bash
cargo build --release
```

The binary lands at `target/release/whisper`.

## 🚀 Quick Start

### 1. Start perception-voice server

```bash
cd ../perception-voice
./target/release/perception-voice serve
```

### 2. Start whisper

```bash
cp config.example.yaml config.yaml
./target/release/whisper
```

### 3. Use it

1. Press **Ctrl+Shift+Space** to start listening (you'll hear a sound)
2. Speak into your microphone
3. Watch the text appear in the active window
4. Press **Ctrl+Shift+Space** to stop listening

With `shortcuts.push_to_talk: true` the same key is held rather than
toggled: hold to listen, release to type. With
`shortcuts.numlock_persistent: true` the NumLock latch drives listening
instead, so dictation stays on without holding anything.

## 🚫 Cancellation

If you start speaking but change your mind:
- Press the hotkey **before** the transcription completes
- Any pending text will be discarded instead of typed

This applies in toggle mode. Under `push_to_talk: true`, releasing the key
is the signal to *type* the buffer, so there is nothing to cancel — use the
NumLock latch or toggle mode if you want the escape hatch.

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

Two settings govern how responsive dictation feels, and they stack:
`audio.post_speech_silence_duration` on the **server** (how much trailing
silence ends an utterance) plus `keyboard.word_mapping_pause_threshold_s`
here (how long a finished utterance is held before typing). The second
exists so multi-word phrases can be matched as a whole; shortening it too
far makes command mappings stop matching.

A v2 config file works unchanged: the `audio`, `transcription` and `vad`
blocks belong to the server now and are accepted and ignored here.

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

The unit must export `DISPLAY` and `XAUTHORITY`. Without them the service
starts cleanly and then cannot type anything — there is no error, just
silence.

## 📖 CLI Reference

```bash
whisper [-v] [-c CONFIG]
```

| Option | Description |
|--------|-------------|
| `-v, --verbose` | Enable verbose logging |
| `-c, --config FILE` | Path to config file (default: `config.yaml`, then `~/.whisper.yaml`) |

`RUST_LOG` overrides `-v` when set.

### Diagnostics

```bash
cargo run --release --bin keycapture -- 20
```

`keycapture` takes input focus and prints whatever is typed into it, which
answers "is anything being typed at all" without keystrokes landing in
whatever window you had open.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  perception-voice serve                         │
│  (Runs Audio8-ASR on the CPU, transcribes audio)                │
│                         │                                       │
│               Unix Socket (IPC)                                 │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                       whisper v3                                 │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────────────────┐ │
│  │ Hotkey      │─▶│ Poll Server  │─▶│ Type to Keyboard      │ │
│  │ Listener    │   │ for Text     │   │ (with word mappings)  │ │
│  └─────────────┘   └──────────────┘   └───────────────────────┘ │
│    X11 GrabKey        25ms poll            X11 XTEST            │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
               ┌─────────────────┐
               │ Active Window   │
               │ (VS Code, etc.) │
               └─────────────────┘
```

Typing goes through XTEST rather than `XSendEvent`: synthetic events from
`XSendEvent` carry a flag that VS Code and most toolkits ignore. Characters
the current layout cannot reach are typed by briefly rebinding a spare
keycode and restoring it afterwards, which is what xdotool and pynput do too.

Hotkeys use `GrabKey`, which matches the modifier mask exactly — so every
combination of the lock modifiers is grabbed, otherwise a hotkey would never
fire while NumLock is on.

## 🙏 Acknowledgments

- [Audio8-ASR](https://huggingface.co/Audio8/Audio8-ASR-0.1B) for the speech recognition model
- [OpenAI Whisper](https://github.com/openai/whisper) for the log-mel audio front end this still follows
- [Silero VAD](https://github.com/snakers4/silero-vad) for voice activity detection
- [ONNX Runtime](https://onnxruntime.ai/) via [`ort`](https://github.com/pykeio/ort) for CPU inference
- [`x11rb`](https://github.com/psychon/x11rb) for keyboard control
- [perception-voice](https://github.com/mikesmullin/perception-voice) for shared STT service
