//! The voice keyboard state machine.
//!
//! Polls perception-voice, buffers utterances until a pause, then either runs
//! a command, pastes via the clipboard, or types the text.
//!
//! Two behaviours are load-bearing and easy to get subtly wrong:
//!
//! - **Word mappings only apply when the whole buffered utterance is a
//!   trigger.** Otherwise dictating a sentence that happens to contain
//!   "proceed" would fire the mapping mid-prose.
//! - **Activation keywords are checked even when listening is off.** They are
//!   the hands-free way back in, so they cannot be gated on the thing they
//!   turn on.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};

use crate::config::Config;
use crate::hotkeys::{self, Hotkey};
use crate::ipc::Client;
use crate::mappings::{self, CommandMappings, Item, WordMappings};
use crate::sound::SoundPlayer;
use crate::x11_keyboard::Keyboard;

const UID: &str = "whisper-keyboard";

/// Magic activation-keyword actions, as opposed to shell commands.
const MAGIC_ACTIONS: &[&str] = &[
    "LISTENING_ON",
    "LISTENING_OFF",
    "LISTENING_TOGGLE",
    "LISTENING_ON_CLIPBOARD",
    "LISTENING_TOGGLE_CLIPBOARD",
];

pub struct App {
    config: Config,
    client: Client,
    keyboard: Keyboard,
    sound: SoundPlayer,
    words: WordMappings,
    commands: CommandMappings,
    activations: Vec<(String, String)>,
    discard: Vec<String>,

    listening: bool,
    clipboard_mode: bool,
    keyword_activated: bool,
    ptt_held: bool,
    numlock_activated: bool,
    output_enabled_at: Option<Instant>,

    pending: Vec<String>,
    pending_last: Option<Instant>,

    started: Instant,
}

impl App {
    pub fn new(config: Config) -> Result<Self> {
        let socket = config.socket_path();
        let keyboard = Keyboard::connect(
            config.keyboard.typing_delay_ms,
            config.keyboard.key_hold_ms,
        )
        .context("connecting to X11")?;

        let mut sound = SoundPlayer::new(config.sounds.enabled);
        for (key, path) in [
            ("start", config.sounds.on_listening_start.as_deref()),
            ("stop", config.sounds.on_listening_stop.as_deref()),
            ("command", config.sounds.on_command_mapping.as_deref()),
            ("word", config.sounds.on_word_buffered.as_deref()),
        ] {
            if let Some(p) = path {
                sound.preload(key, &config.resolve(p))?;
            }
        }

        Ok(Self {
            client: Client::new(&socket, UID),
            keyboard,
            sound,
            words: WordMappings::new(&config.word_mappings),
            commands: CommandMappings::new(&config.command_mappings),
            activations: config
                .activation_keywords
                .iter()
                .map(|(k, v)| (mappings::normalize_trigger(k), v.clone()))
                .collect(),
            discard: config
                .keyboard
                .discard_phrases
                .iter()
                .map(|p| mappings::normalize_trigger(p))
                .collect(),
            config,
            listening: false,
            clipboard_mode: false,
            keyword_activated: false,
            ptt_held: false,
            numlock_activated: false,
            output_enabled_at: None,
            pending: Vec::new(),
            pending_last: None,
            started: Instant::now(),
        })
    }

    fn log(&self, message: &str) {
        if self.config.logging.timestamps {
            let e = self.started.elapsed();
            println!("{}.{:03}s {message}", e.as_secs(), e.subsec_millis());
        } else {
            println!("{message}");
        }
        use std::io::Write;
        let _ = std::io::stdout().flush();
    }

    pub fn run(&mut self, stop: Arc<AtomicBool>) -> Result<()> {
        if self.client.is_server_running() {
            self.log("✓ perception-voice server detected");
        } else {
            self.log(&format!(
                "⚠️  perception-voice server not found at {}",
                self.config.socket_path().display()
            ));
        }

        let mut combos = vec![(
            Hotkey::Sendkeys,
            self.config.shortcuts.toggle_listening.clone(),
        )];
        if let Some(clip) = self.config.shortcuts.toggle_listening_clipboard.clone() {
            combos.push((Hotkey::Clipboard, clip));
        }
        let events = hotkeys::spawn(combos, stop.clone())?;
        self.log(&format!(
            "✓ hotkey enabled: {}",
            self.config.shortcuts.toggle_listening
        ));
        if self.config.shortcuts.numlock_persistent {
            self.log(&format!(
                "✓ NumLock latch enabled (NumLock {} = listening)",
                self.config.shortcuts.numlock_listening_when
            ));
        }
        self.log("🎙️  Ready!");

        // Drop anything the server buffered before we started, so the first
        // poll does not type a backlog.
        let _ = self.client.set_read_marker();

        let interval = Duration::from_millis(self.config.polling.interval_ms);
        let mut last_error: Option<Instant> = None;

        while !stop.load(Ordering::Relaxed) {
            while let Ok(event) = events.try_recv() {
                self.on_hotkey(event);
            }
            self.sync_numlock();

            match self.client.get_transcriptions() {
                Ok(items) => {
                    last_error = None;
                    for item in items {
                        self.on_utterance(&item.text);
                    }
                }
                Err(e) => {
                    // The server restarting is routine; log at most once a
                    // second instead of 40 times.
                    if last_error.map(|t| t.elapsed() > Duration::from_secs(1)).unwrap_or(true) {
                        tracing::warn!("cannot reach perception-voice: {e}");
                        last_error = Some(Instant::now());
                    }
                }
            }

            self.flush_if_paused();
            std::thread::sleep(interval);
        }

        self.log("✓ whisper stopped");
        Ok(())
    }

    fn on_hotkey(&mut self, event: hotkeys::HotkeyEvent) {
        let clipboard = event.hotkey == Hotkey::Clipboard;
        if self.config.shortcuts.push_to_talk {
            if event.pressed {
                self.ptt_held = true;
                self.clipboard_mode = clipboard;
                self.start_listening();
            } else {
                self.ptt_held = false;
                if !self.keyword_activated {
                    let flush = self.config.shortcuts.buffer_until_release;
                    self.stop_listening(flush);
                }
            }
        } else if event.pressed {
            self.clipboard_mode = clipboard;
            if self.listening {
                self.stop_listening(false);
            } else {
                self.start_listening();
            }
        }
    }

    fn start_listening(&mut self) {
        if self.listening {
            return;
        }
        if !self.client.is_server_running() {
            self.log("❌ perception-voice server not running!");
            return;
        }
        self.listening = true;
        self.log("🎤 Listening started");
        self.sound.play("start");
        let _ = self.client.set_read_marker();
        // Gate output briefly so the hotkey's own key noise is not typed.
        self.output_enabled_at = Some(
            Instant::now() + Duration::from_millis(self.config.sounds.listening_state_delay_ms),
        );
    }

    fn stop_listening(&mut self, flush: bool) {
        if !self.listening {
            return;
        }
        self.listening = false;
        self.log("⏸️  Listening stopped");
        self.sound.play("stop");

        if flush {
            // Let the key releases register before typing starts, or the
            // first keystroke can be read as part of the combo.
            let delay = self.config.shortcuts.ptt_release_delay_ms;
            if delay > 0 {
                std::thread::sleep(Duration::from_millis(delay));
            }
            self.flush_pending();
        } else {
            self.pending.clear();
            self.pending_last = None;
        }
    }

    fn sync_numlock(&mut self) {
        if !self.config.shortcuts.numlock_persistent {
            return;
        }
        let Ok(numlock_on) = self.keyboard.numlock_on() else {
            return;
        };
        let want = self.config.numlock_means_listening(numlock_on);

        if want && !self.numlock_activated {
            if !self.client.is_server_running() {
                return;
            }
            self.clipboard_mode = false;
            self.start_listening();
            if self.listening {
                self.numlock_activated = true;
                self.keyword_activated = true;
                self.log("🔢 NumLock latch: listening on");
            }
        } else if !want && self.numlock_activated {
            self.numlock_activated = false;
            self.keyword_activated = false;
            if !self.ptt_held {
                self.stop_listening(true);
            }
            self.log("🔢 NumLock latch: listening off");
        }
    }

    fn on_utterance(&mut self, text: &str) {
        if text.trim().is_empty() {
            return;
        }

        // Activation keywords are deliberately checked even when listening is
        // off; they are how you turn it on hands-free.
        let norm = mappings::normalize_trigger(text);
        if let Some((_, action)) = self.activations.iter().find(|(k, _)| *k == norm) {
            let action = action.clone();
            self.log(&format!("[Keyword]: {text} -> {action}"));
            self.run_activation(text, &action);
            return;
        }

        let ready = self.listening
            && self
                .output_enabled_at
                .map(|t| Instant::now() >= t)
                .unwrap_or(true);
        if !ready {
            return;
        }

        if self.discard.contains(&norm) {
            self.log(&format!("[Discarded]: {text}"));
            return;
        }

        // Hold everything until the key is released in buffer-until-release
        // mode; otherwise flush on the configured pause.
        let hold = self.config.shortcuts.push_to_talk
            && self.config.shortcuts.buffer_until_release
            && !self.keyword_activated;

        if let Some(last) = self.pending_last {
            let gap = last.elapsed().as_secs_f32();
            if gap >= self.config.keyboard.word_mapping_pause_threshold_s && !hold {
                self.flush_pending();
            }
        }
        self.pending.push(text.trim().to_string());
        self.pending_last = Some(Instant::now());

        if hold {
            self.sound.play("word");
        }
    }

    fn flush_if_paused(&mut self) {
        if self.config.shortcuts.push_to_talk
            && self.config.shortcuts.buffer_until_release
            && !self.keyword_activated
        {
            return;
        }
        let Some(last) = self.pending_last else { return };
        if last.elapsed().as_secs_f32() >= self.config.keyboard.word_mapping_pause_threshold_s {
            self.flush_pending();
        }
    }

    fn flush_pending(&mut self) {
        if self.pending.is_empty() {
            return;
        }
        let buffered = std::mem::take(&mut self.pending).join(" ");
        self.pending_last = None;
        let buffered = buffered.trim().to_string();
        if buffered.is_empty() {
            return;
        }

        if let Some(command) = self.commands.lookup(&buffered) {
            self.log(&format!("[Command]: {buffered}"));
            self.run_command(&buffered, &command);
            return;
        }

        if self.clipboard_mode {
            self.log(&format!("[Clipboard]: {buffered}"));
            if let Err(e) = self.type_via_clipboard(&buffered) {
                tracing::error!("clipboard paste failed: {e}");
            }
            return;
        }

        // Word mappings apply only when the utterance *is* a trigger.
        if self.words.is_exact_trigger(&buffered) {
            self.log(&format!("[Mapping]: {buffered}"));
            let items = self.words.apply(&buffered, &read_clipboard);
            self.emit(items);
        } else {
            self.log(&format!("[Typing]: {buffered}"));
            self.emit(vec![Item::Text(strip_trailing_period(&buffered))]);
        }
    }

    fn emit(&mut self, items: Vec<Item>) {
        let mut last_was_newline = false;
        for item in &items {
            match item {
                Item::Text(text) => {
                    if let Err(e) = self.keyboard.type_text(text) {
                        tracing::error!("typing failed: {e}");
                    }
                    last_was_newline = text.ends_with('\n') || text.ends_with('\r');
                }
                Item::Hotkey(combo) => {
                    if let Err(e) = self.keyboard.execute_hotkey(combo) {
                        tracing::error!("hotkey {combo} failed: {e}");
                    }
                    last_was_newline = false;
                }
            }
        }
        // Dictation runs on, so a trailing space is right unless we just
        // ended a line.
        if !items.is_empty() && !last_was_newline {
            let _ = self.keyboard.type_char(' ');
        }
    }

    fn type_via_clipboard(&mut self, text: &str) -> Result<()> {
        let saved = read_clipboard_bytes();
        write_clipboard(text.as_bytes())?;
        self.keyboard.execute_hotkey("ctrl+v")?;
        // Restore what the user had, so dictation does not clobber their
        // clipboard as a side effect.
        if let Some(previous) = saved {
            std::thread::sleep(Duration::from_millis(50));
            let _ = write_clipboard(&previous);
        }
        Ok(())
    }

    fn run_activation(&mut self, phrase: &str, action: &str) {
        if !MAGIC_ACTIONS.contains(&action) {
            self.run_command(phrase, action);
            return;
        }
        self.sound.play("command");
        match action {
            "LISTENING_ON" => {
                self.clipboard_mode = false;
                self.keyword_activated = true;
                self.start_listening();
            }
            "LISTENING_OFF" => {
                self.keyword_activated = false;
                self.stop_listening(true);
            }
            "LISTENING_TOGGLE" => {
                self.clipboard_mode = false;
                self.keyword_activated = !self.listening;
                if self.listening {
                    self.stop_listening(true);
                } else {
                    self.start_listening();
                }
            }
            "LISTENING_ON_CLIPBOARD" => {
                self.clipboard_mode = true;
                self.keyword_activated = true;
                self.start_listening();
            }
            "LISTENING_TOGGLE_CLIPBOARD" => {
                self.clipboard_mode = true;
                self.keyword_activated = !self.listening;
                if self.listening {
                    self.stop_listening(true);
                } else {
                    self.start_listening();
                }
            }
            _ => {}
        }
    }

    fn run_command(&mut self, phrase: &str, command: &str) {
        self.sound.play("command");
        let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into());
        let cwd = self.config.base_dir.clone();
        match std::process::Command::new(shell)
            .arg("-c")
            .arg(command)
            .current_dir(&cwd)
            .stdin(std::process::Stdio::null())
            .spawn()
        {
            Ok(_) => tracing::info!("ran command mapping for {phrase:?}: {command}"),
            Err(e) => {
                tracing::error!("command mapping {phrase:?} failed: {e}");
                self.log(&format!("[Command Error]: {phrase}"));
            }
        }
    }
}

/// A trailing period is an artifact of the model's sentence punctuation, not
/// something the speaker asked for.
pub fn strip_trailing_period(text: &str) -> String {
    let trimmed = text.trim_end();
    trimmed
        .strip_suffix('.')
        .unwrap_or(trimmed)
        .trim_end()
        .to_string()
}

fn read_clipboard() -> String {
    read_clipboard_bytes()
        .map(|b| String::from_utf8_lossy(&b).to_string())
        .unwrap_or_default()
}

fn read_clipboard_bytes() -> Option<Vec<u8>> {
    std::process::Command::new("xclip")
        .args(["-selection", "clipboard", "-o"])
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| o.stdout)
}

fn write_clipboard(data: &[u8]) -> Result<()> {
    use std::io::Write;
    let mut child = std::process::Command::new("xclip")
        .args(["-selection", "clipboard"])
        .stdin(std::process::Stdio::piped())
        .spawn()
        .context("spawning xclip")?;
    child
        .stdin
        .as_mut()
        .context("xclip stdin")?
        .write_all(data)
        .context("writing to xclip")?;
    child.wait().context("waiting for xclip")?;
    Ok(())
}
