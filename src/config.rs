//! YAML configuration, field-compatible with the Python `config.yaml`.
//!
//! The Python-only blocks (`audio`, `transcription`, `vad`) belong to the
//! server now and are accepted and ignored here, so one file can front either
//! build during the switch.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use indexmap::IndexMap;
use serde::Deserialize;

fn d_socket() -> String {
    "tmp/perception-voice/perception.sock".into()
}
fn d_toggle() -> String {
    "ctrl+shift+space".into()
}
fn d_true() -> bool {
    true
}
fn d_ptt_release() -> u64 {
    250
}
fn d_pause() -> f32 {
    0.8
}
fn d_typing_delay() -> u64 {
    3
}
fn d_key_hold() -> u64 {
    3
}
fn d_state_delay() -> u64 {
    50
}
fn d_poll() -> u64 {
    25
}
fn d_numlock_when() -> String {
    "on".into()
}

#[derive(Debug, Clone, Deserialize)]
pub struct PerceptionVoice {
    #[serde(default = "d_socket")]
    pub socket_path: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Shortcuts {
    #[serde(default = "d_toggle")]
    pub toggle_listening: String,
    #[serde(default)]
    pub toggle_listening_clipboard: Option<String>,
    #[serde(default)]
    pub push_to_talk: bool,
    #[serde(default = "d_true")]
    pub buffer_until_release: bool,
    #[serde(default = "d_ptt_release")]
    pub ptt_release_delay_ms: u64,
    #[serde(default)]
    pub numlock_persistent: bool,
    /// `"on"` or `"off"` — which NumLock level means "listening".
    #[serde(default = "d_numlock_when")]
    pub numlock_listening_when: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct KeyboardSettings {
    #[serde(default = "d_pause")]
    pub word_mapping_pause_threshold_s: f32,
    #[serde(default = "d_typing_delay")]
    pub typing_delay_ms: u64,
    #[serde(default = "d_key_hold")]
    pub key_hold_ms: u64,
    #[serde(default)]
    pub discard_phrases: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Sounds {
    #[serde(default = "d_true")]
    pub enabled: bool,
    #[serde(default)]
    pub on_listening_start: Option<String>,
    #[serde(default)]
    pub on_listening_stop: Option<String>,
    #[serde(default)]
    pub on_command_mapping: Option<String>,
    #[serde(default)]
    pub on_word_buffered: Option<String>,
    #[serde(default = "d_state_delay")]
    pub listening_state_delay_ms: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Polling {
    #[serde(default = "d_poll")]
    pub interval_ms: u64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Logging {
    #[serde(default = "d_true")]
    pub timestamps: bool,
    #[serde(default)]
    pub verbose: bool,
}

macro_rules! default_impl {
    ($t:ty, $($field:ident: $value:expr),* $(,)?) => {
        impl Default for $t {
            fn default() -> Self { Self { $($field: $value),* } }
        }
    };
}

default_impl!(PerceptionVoice, socket_path: d_socket());
default_impl!(Shortcuts,
    toggle_listening: d_toggle(),
    toggle_listening_clipboard: None,
    push_to_talk: false,
    buffer_until_release: true,
    ptt_release_delay_ms: d_ptt_release(),
    numlock_persistent: false,
    numlock_listening_when: d_numlock_when(),
);
default_impl!(KeyboardSettings,
    word_mapping_pause_threshold_s: d_pause(),
    typing_delay_ms: d_typing_delay(),
    key_hold_ms: d_key_hold(),
    discard_phrases: Vec::new(),
);
default_impl!(Sounds,
    enabled: true,
    on_listening_start: None,
    on_listening_stop: None,
    on_command_mapping: None,
    on_word_buffered: None,
    listening_state_delay_ms: d_state_delay(),
);
default_impl!(Polling, interval_ms: d_poll());
default_impl!(Logging, timestamps: true, verbose: false);

#[derive(Debug, Clone, Deserialize, Default)]
pub struct Config {
    #[serde(default)]
    pub perception_voice: PerceptionVoice,
    #[serde(default)]
    pub shortcuts: Shortcuts,
    #[serde(default)]
    pub keyboard: KeyboardSettings,
    #[serde(default)]
    pub sounds: Sounds,
    #[serde(default)]
    pub polling: Polling,
    #[serde(default)]
    pub logging: Logging,
    #[serde(default)]
    pub word_mappings: IndexMap<String, String>,
    #[serde(default)]
    pub command_mappings: IndexMap<String, String>,
    #[serde(default)]
    pub activation_keywords: IndexMap<String, String>,

    #[serde(skip)]
    pub base_dir: PathBuf,
}

impl Config {
    pub fn load(path: Option<&Path>) -> Result<Self> {
        let path = path.map(Path::to_path_buf).unwrap_or_else(|| {
            // Same search order as the Python: CWD, then the home dotfile.
            let cwd = PathBuf::from("config.yaml");
            if cwd.exists() {
                return cwd;
            }
            PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".whisper.yaml")
        });
        let text = std::fs::read_to_string(&path)
            .with_context(|| format!("reading config {}", path.display()))?;
        let mut config: Config = serde_yaml::from_str(&text)
            .with_context(|| format!("parsing config {}", path.display()))?;
        config.base_dir = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .map(Path::to_path_buf)
            .unwrap_or_else(|| PathBuf::from("."));
        Ok(config)
    }

    pub fn resolve(&self, value: &str) -> PathBuf {
        let p = Path::new(value);
        if p.is_absolute() {
            p.to_path_buf()
        } else if let Some(rest) = value.strip_prefix("~/") {
            PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| ".".into())).join(rest)
        } else {
            self.base_dir.join(p)
        }
    }

    pub fn socket_path(&self) -> PathBuf {
        self.resolve(&self.perception_voice.socket_path)
    }

    /// True when the NumLock latch should be read as "listening".
    pub fn numlock_means_listening(&self, numlock_on: bool) -> bool {
        if self.shortcuts.numlock_listening_when.eq_ignore_ascii_case("off") {
            !numlock_on
        } else {
            numlock_on
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_fill_in_for_an_empty_document() {
        let c: Config = serde_yaml::from_str("{}").unwrap();
        assert_eq!(c.shortcuts.toggle_listening, "ctrl+shift+space");
        assert_eq!(c.polling.interval_ms, 25);
        assert_eq!(c.keyboard.typing_delay_ms, 3);
        assert!(c.sounds.enabled);
    }

    #[test]
    fn server_side_blocks_are_accepted_and_ignored() {
        let yaml = r#"
audio:
  sample_rate: 16000
transcription:
  model: "large-v3"
vad:
  webrtc_sensitivity: 3
shortcuts:
  toggle_listening: "alt+space"
  push_to_talk: true
"#;
        let c: Config = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(c.shortcuts.toggle_listening, "alt+space");
        assert!(c.shortcuts.push_to_talk);
    }

    #[test]
    fn mappings_preserve_file_order() {
        // Longest-first precedence is computed later, but a stable iteration
        // order keeps behaviour reproducible.
        let yaml = r#"
word_mappings:
  new line: "\n"
  insert bullet: "- "
  proceed: "proceed\n"
"#;
        let c: Config = serde_yaml::from_str(yaml).unwrap();
        let keys: Vec<&str> = c.word_mappings.keys().map(String::as_str).collect();
        assert_eq!(keys, vec!["new line", "insert bullet", "proceed"]);
    }

    #[test]
    fn numlock_polarity_can_be_inverted() {
        let mut c = Config::default();
        c.shortcuts.numlock_listening_when = "off".into();
        assert!(c.numlock_means_listening(false));
        assert!(!c.numlock_means_listening(true));

        c.shortcuts.numlock_listening_when = "on".into();
        assert!(c.numlock_means_listening(true));
        assert!(!c.numlock_means_listening(false));
    }

    #[test]
    fn paths_resolve_against_the_config_directory() {
        let mut c = Config::default();
        c.base_dir = PathBuf::from("/opt/w");
        assert_eq!(
            c.resolve("sfx/on.wav"),
            PathBuf::from("/opt/w/sfx/on.wav")
        );
        assert_eq!(c.resolve("/abs/x.wav"), PathBuf::from("/abs/x.wav"));
    }
}
