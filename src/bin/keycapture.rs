//! Test helper: take input focus and print whatever gets typed into us.
//!
//! Lets the whole dictation chain be exercised without keystrokes landing in
//! whatever the user happens to have open.
//!
//!     keycapture [seconds]
use std::time::{Duration, Instant};

use x11rb::connection::Connection;
use x11rb::protocol::xproto::{
    ConnectionExt as _, CreateWindowAux, EventMask, InputFocus, WindowClass,
};
use x11rb::protocol::Event;
use x11rb::rust_connection::RustConnection;
use x11rb::COPY_DEPTH_FROM_PARENT;

fn main() -> anyhow::Result<()> {
    let seconds: u64 = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(20);

    let (conn, screen_num) = RustConnection::connect(None)?;
    let screen = &conn.setup().roots[screen_num];
    let previous = conn.get_input_focus()?.reply()?.focus;

    let window = conn.generate_id()?;
    conn.create_window(
        COPY_DEPTH_FROM_PARENT, window, screen.root, 0, 0, 1, 1, 0,
        WindowClass::INPUT_OUTPUT, screen.root_visual,
        &CreateWindowAux::new()
            .event_mask(EventMask::KEY_PRESS | EventMask::KEY_RELEASE)
            .override_redirect(1),
    )?;
    conn.map_window(window)?;
    conn.flush()?;
    std::thread::sleep(Duration::from_millis(150));
    conn.set_input_focus(InputFocus::PARENT, window, x11rb::CURRENT_TIME)?;
    conn.flush()?;
    eprintln!("keycapture: focused, listening for {seconds}s");

    let min = conn.setup().min_keycode;
    let max = conn.setup().max_keycode;
    let mapping = conn.get_keyboard_mapping(min, max - min + 1)?.reply()?;
    let per = mapping.keysyms_per_keycode as usize;

    let mut typed = String::new();
    let mut shift = false;
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < deadline {
        match conn.poll_for_event()? {
            Some(Event::KeyPress(e)) => {
                let base = (e.detail - min) as usize * per;
                let un = mapping.keysyms.get(base).copied().unwrap_or(0);
                let sh = mapping.keysyms.get(base + 1).copied().unwrap_or(0);
                if un == 0xffe1 || un == 0xffe2 { shift = true; continue; }
                let sym = if shift && sh != 0 { sh } else { un };
                match sym {
                    0xff0d => typed.push('\n'),
                    0xff09 => typed.push('\t'),
                    s if s < 0x100 => {
                        if let Some(c) = char::from_u32(s) { typed.push(c); }
                    }
                    s if s >= 0x0100_0000 => {
                        if let Some(c) = char::from_u32(s - 0x0100_0000) { typed.push(c); }
                    }
                    _ => {}
                }
            }
            Some(Event::KeyRelease(e)) => {
                let base = (e.detail - min) as usize * per;
                let un = mapping.keysyms.get(base).copied().unwrap_or(0);
                if un == 0xffe1 || un == 0xffe2 { shift = false; }
            }
            Some(_) => {}
            None => std::thread::sleep(Duration::from_millis(10)),
        }
    }

    conn.set_input_focus(InputFocus::PARENT, previous, x11rb::CURRENT_TIME).ok();
    conn.destroy_window(window).ok();
    conn.flush().ok();
    println!("CAPTURED: {typed:?}");
    Ok(())
}
