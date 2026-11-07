//! Global hotkeys via X11 `GrabKey`.
//!
//! `GrabKey` rather than monitoring all input: the service only cares about a
//! couple of combos, and a grab both delivers them regardless of focus and
//! stops the focused application from also acting on them — which is what you
//! want from a dictation hotkey.
//!
//! The subtlety is that a grab matches the modifier mask *exactly*. With
//! NumLock on (as it is whenever the NumLock latch is in use) the real mask
//! includes Mod2, so a single grab would simply never fire. Every combination
//! of the lock modifiers has to be grabbed separately.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use anyhow::{anyhow, Context, Result};
use crossbeam_channel::{unbounded, Receiver};
use x11rb::connection::Connection;
use x11rb::protocol::xproto::{ConnectionExt as _, GrabMode, ModMask};
use x11rb::protocol::Event;
use x11rb::rust_connection::RustConnection;

use crate::x11_keyboard::named_keysym;

/// Which configured combo fired.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Hotkey {
    Sendkeys,
    Clipboard,
}

#[derive(Debug, Clone, Copy)]
pub struct HotkeyEvent {
    pub hotkey: Hotkey,
    pub pressed: bool,
}

/// Lock modifiers that may be set independently of the combo.
fn lock_mask_variants() -> [u16; 4] {
    let caps = u16::from(ModMask::LOCK);
    let num = u16::from(ModMask::M2);
    [0, caps, num, caps | num]
}

/// Parse `"ctrl+shift+space"` into a modifier mask and the main keysym.
pub fn parse_combo(combo: &str) -> Result<(u16, u32)> {
    let mut mask = 0u16;
    let mut main: Option<u32> = None;
    for part in combo.split('+') {
        let part = part.trim().to_ascii_lowercase();
        match part.as_str() {
            "ctrl" | "control" => mask |= u16::from(ModMask::CONTROL),
            "shift" => mask |= u16::from(ModMask::SHIFT),
            "alt" => mask |= u16::from(ModMask::M1),
            "super" | "cmd" | "meta" => mask |= u16::from(ModMask::M4),
            other => {
                let sym = named_keysym(other)
                    .ok_or_else(|| anyhow!("unknown key in hotkey {combo:?}: {other:?}"))?;
                main = Some(sym);
            }
        }
    }
    Ok((mask, main.ok_or_else(|| anyhow!("hotkey {combo:?} has no non-modifier key"))?))
}

/// Grab the given combos and stream press/release events.
pub fn spawn(combos: Vec<(Hotkey, String)>, stop: Arc<AtomicBool>) -> Result<Receiver<HotkeyEvent>> {
    let (tx, rx) = unbounded();
    let (conn, screen_num) =
        RustConnection::connect(None).context("connecting to X for hotkeys")?;
    let root = conn.setup().roots[screen_num].root;

    // Resolve keysyms to keycodes on this connection's mapping.
    let min = conn.setup().min_keycode;
    let max = conn.setup().max_keycode;
    let mapping = conn.get_keyboard_mapping(min, max - min + 1)?.reply()?;
    let per = mapping.keysyms_per_keycode as usize;

    let keycode_of = |keysym: u32| -> Option<u8> {
        mapping
            .keysyms
            .chunks(per)
            .position(|group| group.iter().any(|&k| k == keysym))
            .map(|i| min + i as u8)
    };

    let mut grabbed: Vec<(u8, u16, Hotkey)> = Vec::new();
    for (hotkey, combo) in &combos {
        let (mask, keysym) = parse_combo(combo)?;
        let keycode = keycode_of(keysym)
            .ok_or_else(|| anyhow!("no keycode bound to the main key of {combo:?}"))?;
        for extra in lock_mask_variants() {
            conn.grab_key(
                true, // report events to the focused window too
                root,
                ModMask::from(mask | extra),
                keycode,
                GrabMode::ASYNC,
                GrabMode::ASYNC,
            )?
            .check()
            .with_context(|| {
                format!("grabbing {combo:?}; another application may already hold it")
            })?;
        }
        grabbed.push((keycode, mask, *hotkey));
        tracing::info!("registered hotkey {combo} -> {hotkey:?}");
    }
    conn.flush()?;

    std::thread::Builder::new()
        .name("hotkeys".into())
        .spawn(move || {
            let lock_bits = u16::from(ModMask::LOCK) | u16::from(ModMask::M2);
            while !stop.load(Ordering::Relaxed) {
                match conn.poll_for_event() {
                    Ok(Some(event)) => {
                        let (keycode, state, pressed) = match event {
                            Event::KeyPress(e) => (e.detail, u16::from(e.state), true),
                            Event::KeyRelease(e) => (e.detail, u16::from(e.state), false),
                            _ => continue,
                        };
                        // Ignore the lock bits when matching, since they were
                        // only in the grab to make it fire at all.
                        let effective = state & !lock_bits;
                        if let Some((_, _, hotkey)) = grabbed
                            .iter()
                            .find(|(kc, mask, _)| *kc == keycode && *mask == effective)
                        {
                            let _ = tx.send(HotkeyEvent { hotkey: *hotkey, pressed });
                        }
                    }
                    Ok(None) => std::thread::sleep(std::time::Duration::from_millis(5)),
                    Err(e) => {
                        tracing::error!("hotkey listener lost the X connection: {e}");
                        break;
                    }
                }
            }
            tracing::info!("hotkey listener stopped");
        })
        .context("spawning the hotkey listener")?;

    Ok(rx)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_three_part_combo() {
        let (mask, sym) = parse_combo("ctrl+shift+space").unwrap();
        assert_eq!(
            mask,
            u16::from(ModMask::CONTROL) | u16::from(ModMask::SHIFT)
        );
        assert_eq!(sym, 0x0020);
    }

    #[test]
    fn parses_alt_space() {
        let (mask, sym) = parse_combo("alt+space").unwrap();
        assert_eq!(mask, u16::from(ModMask::M1));
        assert_eq!(sym, 0x0020);
    }

    #[test]
    fn parses_a_letter_combo() {
        let (mask, sym) = parse_combo("ctrl+z").unwrap();
        assert_eq!(mask, u16::from(ModMask::CONTROL));
        assert_eq!(sym, 0x7a);
    }

    #[test]
    fn rejects_a_combo_with_no_main_key() {
        assert!(parse_combo("ctrl+shift").is_err());
    }

    #[test]
    fn rejects_an_unknown_key_name() {
        assert!(parse_combo("ctrl+nonsense").is_err());
    }

    #[test]
    fn lock_variants_cover_caps_and_num_combinations() {
        let v = lock_mask_variants();
        assert_eq!(v.len(), 4);
        assert!(v.contains(&0));
        // NumLock alone must be covered, or the latch config breaks hotkeys.
        assert!(v.contains(&u16::from(ModMask::M2)));
    }
}
