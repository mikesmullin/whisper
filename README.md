# 👄 whisper v3

A voice keyboard that types what you say.

| Version | Implementation |
|---------|----------------|
| `v3` (default) | Rust client: X11 XTEST typing, no runtime deps (this branch) |
| `v2` | Python client; delegates STT to perception-voice |
| `v1` | Standalone Python with a built-in Whisper model (GPU required) |

## What it does

Polls [perception-voice](https://github.com/mikesmullin/perception-voice) for
finished utterances and types them into whatever window has focus, as real key
events. On top of plain dictation:

- **word mappings** — `"new line"` → `\n`, `"now undo"` → `ctrl+z`
- **command mappings** — spoken phrases run shell commands, with `*` wildcards
  and `$WORDS` capture
- **activation keywords** — hands-free `"work activate"` / `"work deactivate"`,
  checked even while listening is off
- **clipboard-paste mode** — for text that must arrive atomically
- **NumLock latch** — a persistent listening mode rather than push-to-talk
- **discard phrases** — drops the sounds models hallucinate from coughs

## Why Rust

The v2 Python client started in about a second and pulled in pygame and pynput;
this is a single static binary that starts in milliseconds. Nothing about the
*behaviour* needed changing — the mapping semantics are carried over
deliberately, down to the trailing-space rule — so the win is startup, memory,
and having no interpreter in the dictation path.

Typing goes through XTEST rather than `XSendEvent`: synthetic events carry a
`send_event` flag that VS Code and most toolkits ignore. Characters the current
layout cannot reach are typed by briefly rebinding a spare keycode, which is
what xdotool and pynput do too.

## Requirements

- Linux with X11 (Wayland is not supported: XTEST and key grabs are X11)
- a running perception-voice server
- `xclip`, for clipboard-paste mode and the `{{clipboard}}` placeholder

## Build and run

    cargo build --release
    ./target/release/whisper            # reads ./config.yaml, then ~/.whisper.yaml

Copy `config.example.yaml` to `config.yaml` to start. A v2 config works
unchanged: the `audio`, `transcription` and `vad` blocks belong to the server
now and are accepted and ignored here.

`src/bin/keycapture.rs` is a diagnostic, not a test: it takes input focus and
prints whatever gets typed into it, which answers "is anything being typed at
all" without keystrokes landing in whatever you had open.

    cargo run --release --bin keycapture -- 20
