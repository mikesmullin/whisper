//! Sound effects for listening-state changes.
//!
//! Each cue is loaded once and played from memory: these fire on every hotkey
//! press, and re-reading a wav from disk on the UI path is both slower and a
//! source of stutter. A missing or unreadable file degrades to silence with a
//! warning, never an error — losing a beep must not stop dictation.

use std::collections::HashMap;
use std::io::Cursor;
use std::path::Path;
use std::sync::Arc;

use anyhow::Result;

pub struct SoundPlayer {
    enabled: bool,
    device: Option<rodio::stream::MixerDeviceSink>,
    clips: HashMap<String, Arc<Vec<u8>>>,
}

impl SoundPlayer {
    pub fn new(enabled: bool) -> Self {
        let device = if enabled {
            match rodio::stream::DeviceSinkBuilder::open_default_sink() {
                Ok(d) => Some(d),
                Err(e) => {
                    tracing::warn!("no audio output for sound effects ({e}); continuing muted");
                    None
                }
            }
        } else {
            None
        };
        Self { enabled: enabled && device.is_some(), device, clips: HashMap::new() }
    }

    pub fn preload(&mut self, key: &str, path: &Path) -> Result<()> {
        if !self.enabled {
            return Ok(());
        }
        match std::fs::read(path) {
            Ok(bytes) => {
                self.clips.insert(key.to_string(), Arc::new(bytes));
            }
            Err(e) => tracing::warn!("sound {key} unavailable at {}: {e}", path.display()),
        }
        Ok(())
    }

    pub fn play(&self, key: &str) {
        if !self.enabled {
            return;
        }
        let (Some(device), Some(bytes)) = (self.device.as_ref(), self.clips.get(key)) else {
            return;
        };
        let cursor = Cursor::new(bytes.as_ref().clone());
        match rodio::Decoder::new(cursor) {
            Ok(source) => {
                let player = rodio::Player::connect_new(device.mixer());
                player.append(source);
                // Detach: a cue must never hold up the keystrokes behind it.
                player.detach();
            }
            Err(e) => tracing::warn!("could not decode sound {key}: {e}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_player_is_inert() {
        let p = SoundPlayer::new(false);
        p.play("anything"); // must not panic
    }

    #[test]
    fn missing_file_warns_rather_than_failing() {
        let mut p = SoundPlayer::new(false);
        assert!(p.preload("x", Path::new("/nonexistent/none.wav")).is_ok());
        p.play("x");
    }
}
