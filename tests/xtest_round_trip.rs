//! Verify that synthesized keystrokes actually arrive as key events.
//!
//! Unit tests can only check the keysym arithmetic. Whether XTEST reaches an
//! application is a property of the running X server, the layout, and the
//! spare-keycode dance — exactly the part that silently types nothing when it
//! is wrong. So: create a window, focus it, synthesize text, and read the key
//! events back.
//!
//! The test briefly takes input focus and restores it afterwards. It is
//! skipped when there is no reachable X server (CI), and can be skipped
//! explicitly with `WHISPER_SKIP_X11_TESTS=1` so it never interrupts someone
//! mid-sentence.

use std::time::{Duration, Instant};

use x11rb::connection::Connection;
use x11rb::protocol::xproto::{
    ConnectionExt as _, CreateWindowAux, EventMask, InputFocus, WindowClass,
};
use x11rb::protocol::Event;
use x11rb::rust_connection::RustConnection;
use x11rb::COPY_DEPTH_FROM_PARENT;

fn should_skip() -> bool {
    if std::env::var("WHISPER_SKIP_X11_TESTS").is_ok() {
        eprintln!("skipping: WHISPER_SKIP_X11_TESTS is set");
        return true;
    }
    if std::env::var("DISPLAY").is_err() {
        eprintln!("skipping: no DISPLAY");
        return true;
    }
    false
}

/// keycode -> unshifted/shifted keysyms, for decoding events back to text.
fn keysym_table(conn: &RustConnection) -> (u8, usize, Vec<u32>) {
    let min = conn.setup().min_keycode;
    let max = conn.setup().max_keycode;
    let count = max - min + 1;
    let reply = conn
        .get_keyboard_mapping(min, count)
        .unwrap()
        .reply()
        .unwrap();
    (min, reply.keysyms_per_keycode as usize, reply.keysyms)
}

#[test]
fn synthesized_keystrokes_are_delivered_as_key_events() {
    if should_skip() {
        return;
    }
    let Ok((conn, screen_num)) = RustConnection::connect(None) else {
        eprintln!("skipping: cannot reach the X server");
        return;
    };
    let screen = &conn.setup().roots[screen_num];
    let root = screen.root;

    // Remember who had focus so the desktop is left as we found it.
    let previous_focus = conn.get_input_focus().unwrap().reply().unwrap().focus;

    let window = conn.generate_id().unwrap();
    conn.create_window(
        COPY_DEPTH_FROM_PARENT,
        window,
        root,
        0,
        0,
        1,
        1,
        0,
        WindowClass::INPUT_OUTPUT,
        screen.root_visual,
        &CreateWindowAux::new()
            .event_mask(EventMask::KEY_PRESS | EventMask::KEY_RELEASE)
            .override_redirect(1),
    )
    .unwrap();
    conn.map_window(window).unwrap();
    conn.flush().unwrap();
    std::thread::sleep(Duration::from_millis(120));
    conn.set_input_focus(InputFocus::PARENT, window, x11rb::CURRENT_TIME)
        .unwrap();
    conn.flush().unwrap();
    std::thread::sleep(Duration::from_millis(120));

    // Type through the same code path the service uses.
    let mut kb = whisper::x11_keyboard::Keyboard::connect(1, 1).expect("keyboard");
    let expected = "hi there";
    kb.type_text(expected).expect("type_text");
    conn.flush().unwrap();

    // Collect key presses for a moment.
    let (min_keycode, per, keysyms) = keysym_table(&conn);
    let mut typed = String::new();
    let deadline = Instant::now() + Duration::from_secs(3);
    let mut shift_held = false;
    while Instant::now() < deadline {
        match conn.poll_for_event().unwrap() {
            Some(Event::KeyPress(e)) => {
                let base = (e.detail - min_keycode) as usize * per;
                let unshifted = keysyms.get(base).copied().unwrap_or(0);
                let shifted = keysyms.get(base + 1).copied().unwrap_or(0);
                if unshifted == 0xffe1 || unshifted == 0xffe2 {
                    shift_held = true;
                    continue;
                }
                let sym = if shift_held && shifted != 0 { shifted } else { unshifted };
                if let Some(c) = char::from_u32(sym) {
                    if sym < 0x100 {
                        typed.push(c);
                    }
                }
            }
            Some(Event::KeyRelease(e)) => {
                let base = (e.detail - min_keycode) as usize * per;
                let unshifted = keysyms.get(base).copied().unwrap_or(0);
                if unshifted == 0xffe1 || unshifted == 0xffe2 {
                    shift_held = false;
                }
            }
            Some(_) => {}
            None => {
                if typed.len() >= expected.len() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    }

    // Restore the desktop before asserting, so a failure does not also leave
    // focus on a destroyed window.
    conn.set_input_focus(InputFocus::PARENT, previous_focus, x11rb::CURRENT_TIME)
        .ok();
    conn.destroy_window(window).ok();
    conn.flush().ok();

    assert_eq!(
        typed, expected,
        "XTEST keystrokes did not arrive as typed; got {typed:?}"
    );
}

#[test]
fn numlock_state_is_readable() {
    if should_skip() {
        return;
    }
    let Ok(mut kb) = whisper::x11_keyboard::Keyboard::connect(1, 1) else {
        eprintln!("skipping: cannot reach the X server");
        return;
    };
    // The NumLock latch drives persistent listening, so an unreadable state
    // would silently disable it. Only assert that it reads without error.
    match kb.numlock_on() {
        Ok(state) => eprintln!("NumLock is currently {}", if state { "on" } else { "off" }),
        Err(e) => panic!("could not read NumLock state: {e}"),
    }
    let _ = &mut kb;
}
