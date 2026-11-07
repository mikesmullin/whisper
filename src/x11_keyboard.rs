//! X11 keystroke synthesis via the XTEST extension.
//!
//! XTEST rather than `XSendEvent` deliberately: synthetic events from
//! `XSendEvent` carry a `send_event` flag, and applications including VS Code
//! and most toolkits ignore them. XTEST events are indistinguishable from real
//! hardware input, which is the whole point of a voice *keyboard*.
//!
//! Characters the current layout cannot reach are typed by temporarily
//! rebinding a spare keycode to the needed keysym, pressing it, and restoring
//! the old binding. That is how xdotool and pynput do it too; there is no way
//! to inject a keysym directly.

use std::collections::HashMap;

use anyhow::{anyhow, Context, Result};
use x11rb::connection::Connection;
use x11rb::protocol::xproto::{ConnectionExt as _, GetKeyboardMappingReply, ModMask};
use x11rb::protocol::xtest::ConnectionExt as _;
use x11rb::rust_connection::RustConnection;

const KEY_PRESS: u8 = 2;
const KEY_RELEASE: u8 = 3;

/// Modifier keysyms we may need to hold down for a combo.
const SHIFT_L: u32 = 0xffe1;
const CONTROL_L: u32 = 0xffe3;
const ALT_L: u32 = 0xffe9;
const SUPER_L: u32 = 0xffeb;

pub struct Keyboard {
    conn: RustConnection,
    root: x11rb::protocol::xproto::Window,
    min_keycode: u8,
    keysyms_per_keycode: u8,
    /// keysym -> (keycode, needs_shift)
    map: HashMap<u32, (u8, bool)>,
    /// A keycode with no bindings, borrowed for unmappable characters.
    spare_keycode: Option<u8>,
    typing_delay_ms: u64,
    key_hold_ms: u64,
}

impl Keyboard {
    pub fn connect(typing_delay_ms: u64, key_hold_ms: u64) -> Result<Self> {
        let (conn, screen_num) =
            RustConnection::connect(None).context("connecting to the X server")?;
        let root = conn.setup().roots[screen_num].root;

        // XTEST must be present, or every keystroke silently does nothing.
        conn.xtest_get_version(2, 2)
            .context("querying XTEST")?
            .reply()
            .context("XTEST extension unavailable; cannot synthesize keystrokes")?;

        let min_keycode = conn.setup().min_keycode;
        let max_keycode = conn.setup().max_keycode;
        let count = (max_keycode - min_keycode) as u16 + 1;
        let mapping = conn
            .get_keyboard_mapping(min_keycode, count.try_into().unwrap_or(u8::MAX))?
            .reply()
            .context("reading the keyboard mapping")?;

        let mut kb = Self {
            conn,
            root,
            min_keycode,
            keysyms_per_keycode: mapping.keysyms_per_keycode,
            map: HashMap::new(),
            spare_keycode: None,
            typing_delay_ms,
            key_hold_ms,
        };
        kb.index_mapping(&mapping);
        Ok(kb)
    }

    fn index_mapping(&mut self, mapping: &GetKeyboardMappingReply) {
        let per = mapping.keysyms_per_keycode as usize;
        self.map.clear();
        self.spare_keycode = None;

        for (i, group) in mapping.keysyms.chunks(per).enumerate() {
            let keycode = self.min_keycode + i as u8;
            if group.iter().all(|&k| k == 0) {
                // Unbound: usable as scratch space for unmappable characters.
                if self.spare_keycode.is_none() {
                    self.spare_keycode = Some(keycode);
                }
                continue;
            }
            // Index 0 is unshifted, 1 is shifted. Later groups are other
            // layout levels, which this does not try to reach.
            if let Some(&unshifted) = group.first() {
                if unshifted != 0 {
                    self.map.entry(unshifted).or_insert((keycode, false));
                }
            }
            if let Some(&shifted) = group.get(1) {
                if shifted != 0 {
                    self.map.entry(shifted).or_insert((keycode, true));
                }
            }
        }
    }

    fn fake_key(&self, kind: u8, keycode: u8) -> Result<()> {
        self.conn
            .xtest_fake_input(kind, keycode, 0, self.root, 0, 0, 0)
            .context("xtest_fake_input")?;
        Ok(())
    }

    fn tap(&self, keycode: u8) -> Result<()> {
        self.fake_key(KEY_PRESS, keycode)?;
        if self.key_hold_ms > 0 {
            self.conn.flush()?;
            std::thread::sleep(std::time::Duration::from_millis(self.key_hold_ms));
        }
        self.fake_key(KEY_RELEASE, keycode)?;
        self.conn.flush()?;
        Ok(())
    }

    /// Type one character, borrowing a spare keycode if the layout lacks it.
    pub fn type_char(&mut self, ch: char) -> Result<()> {
        let keysym = char_to_keysym(ch);

        if let Some(&(keycode, shift)) = self.map.get(&keysym) {
            if shift {
                let (shift_kc, _) = *self
                    .map
                    .get(&SHIFT_L)
                    .ok_or_else(|| anyhow!("no keycode bound to Shift"))?;
                self.fake_key(KEY_PRESS, shift_kc)?;
                let r = self.tap(keycode);
                self.fake_key(KEY_RELEASE, shift_kc)?;
                self.conn.flush()?;
                r?;
            } else {
                self.tap(keycode)?;
            }
        } else {
            self.type_via_spare_keycode(keysym)?;
        }

        if self.typing_delay_ms > 0 {
            std::thread::sleep(std::time::Duration::from_millis(self.typing_delay_ms));
        }
        Ok(())
    }

    /// Rebind a spare keycode to `keysym`, tap it, then put it back.
    fn type_via_spare_keycode(&mut self, keysym: u32) -> Result<()> {
        let keycode = self
            .spare_keycode
            .ok_or_else(|| anyhow!("no spare keycode available to type keysym {keysym:#x}"))?;
        let per = self.keysyms_per_keycode as usize;

        let syms = vec![keysym; per];
        self.conn
            .change_keyboard_mapping(1, keycode, self.keysyms_per_keycode, &syms)?
            .check()
            .context("rebinding a spare keycode")?;
        // The server must have applied the new mapping before the key event,
        // or the press resolves against the old (empty) binding.
        self.conn.flush()?;
        std::thread::sleep(std::time::Duration::from_millis(1));

        let result = self.tap(keycode);

        // Restore unconditionally: leaving a rebound keycode behind would
        // corrupt the user's layout for every other application.
        let cleared = vec![0u32; per];
        match self
            .conn
            .change_keyboard_mapping(1, keycode, self.keysyms_per_keycode, &cleared)
        {
            Ok(cookie) => {
                if let Err(e) = cookie.check() {
                    tracing::warn!("could not restore spare keycode {keycode}: {e}");
                }
            }
            Err(e) => tracing::warn!("could not restore spare keycode {keycode}: {e}"),
        }
        self.conn.flush()?;
        result
    }

    pub fn type_text(&mut self, text: &str) -> Result<()> {
        for ch in text.chars() {
            if let Err(e) = self.type_char(ch) {
                tracing::warn!("could not type {ch:?}: {e}");
            }
        }
        Ok(())
    }

    /// Execute a combo like `ctrl+shift+space` or `ctrl+z`.
    pub fn execute_hotkey(&mut self, combo: &str) -> Result<()> {
        let mut modifiers: Vec<u8> = Vec::new();
        let mut main: Option<u8> = None;

        for part in combo.split('+') {
            let part = part.trim().to_ascii_lowercase();
            let keysym = match part.as_str() {
                "ctrl" | "control" => Some(CONTROL_L),
                "shift" => Some(SHIFT_L),
                "alt" => Some(ALT_L),
                "super" | "cmd" | "meta" => Some(SUPER_L),
                other => named_keysym(other),
            };
            let keysym = keysym.ok_or_else(|| anyhow!("unknown key in hotkey: {part:?}"))?;
            let (keycode, _) = *self
                .map
                .get(&keysym)
                .ok_or_else(|| anyhow!("no keycode bound to {part:?}"))?;

            if matches!(keysym, CONTROL_L | SHIFT_L | ALT_L | SUPER_L) {
                modifiers.push(keycode);
            } else {
                main = Some(keycode);
            }
        }

        let main = main.ok_or_else(|| anyhow!("hotkey {combo:?} has no non-modifier key"))?;
        for &m in &modifiers {
            self.fake_key(KEY_PRESS, m)?;
        }
        self.conn.flush()?;
        let result = self.tap(main);
        // Release modifiers even if the main key failed, or they stay stuck
        // down and the desktop becomes unusable.
        for &m in modifiers.iter().rev() {
            let _ = self.fake_key(KEY_RELEASE, m);
        }
        self.conn.flush()?;
        result
    }

    /// Whether NumLock is currently on, read from the modifier state rather
    /// than from key events (a latch has a level, not an edge).
    pub fn numlock_on(&self) -> Result<bool> {
        let mask = self.numlock_mask()?;
        if mask == 0 {
            return Err(anyhow!("NumLock is not mapped as an X modifier"));
        }
        let pointer = self.conn.query_pointer(self.root)?.reply()?;
        Ok(u16::from(pointer.mask) & mask != 0)
    }

    fn numlock_mask(&self) -> Result<u16> {
        let reply = self.conn.get_modifier_mapping()?.reply()?;
        let per = reply.keycodes_per_modifier() as usize;
        let num_lock_keysym = 0xff7f; // XK_Num_Lock
        let target = self
            .map
            .get(&num_lock_keysym)
            .map(|&(kc, _)| kc)
            .ok_or_else(|| anyhow!("no keycode bound to Num_Lock"))?;

        // Modifier order: Shift, Lock, Control, Mod1..Mod5
        for (index, group) in reply.keycodes.chunks(per).enumerate() {
            if group.contains(&target) {
                return Ok(match index {
                    0 => u16::from(ModMask::SHIFT),
                    1 => u16::from(ModMask::LOCK),
                    2 => u16::from(ModMask::CONTROL),
                    3 => u16::from(ModMask::M1),
                    4 => u16::from(ModMask::M2),
                    5 => u16::from(ModMask::M3),
                    6 => u16::from(ModMask::M4),
                    7 => u16::from(ModMask::M5),
                    _ => 0,
                });
            }
        }
        Ok(0)
    }

    pub fn tap_numlock(&mut self) -> Result<()> {
        let (keycode, _) = *self
            .map
            .get(&0xff7f)
            .ok_or_else(|| anyhow!("no keycode bound to Num_Lock"))?;
        self.tap(keycode)
    }
}

/// Unicode -> X11 keysym.
///
/// Latin-1 maps directly; everything else uses the 0x01000000 + codepoint
/// form, which is how X represents arbitrary Unicode.
pub fn char_to_keysym(ch: char) -> u32 {
    match ch {
        '\n' | '\r' => 0xff0d, // Return
        '\t' => 0xff09,        // Tab
        '\u{8}' => 0xff08,     // BackSpace
        '\u{1b}' => 0xff1b,    // Escape
        c if (c as u32) < 0x100 => c as u32,
        c => 0x0100_0000 + c as u32,
    }
}

/// Keysym for a name usable in a hotkey string.
pub fn named_keysym(name: &str) -> Option<u32> {
    Some(match name {
        "space" => 0x0020,
        "enter" | "return" => 0xff0d,
        "tab" => 0xff09,
        "backspace" => 0xff08,
        "escape" | "esc" => 0xff1b,
        "delete" | "del" => 0xffff,
        "home" => 0xff50,
        "left" => 0xff51,
        "up" => 0xff52,
        "right" => 0xff53,
        "down" => 0xff54,
        "page_up" | "pageup" => 0xff55,
        "page_down" | "pagedown" => 0xff56,
        "end" => 0xff57,
        "insert" => 0xff63,
        "num_lock" | "numlock" => 0xff7f,
        f if f.starts_with('f') && f.len() >= 2 => {
            let n: u32 = f[1..].parse().ok()?;
            if (1..=24).contains(&n) {
                0xffbd + n
            } else {
                return None;
            }
        }
        s if s.chars().count() == 1 => char_to_keysym(s.chars().next()?),
        _ => return None,
    })
}
