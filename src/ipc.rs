//! Client half of the perception-voice protocol: 4-byte big-endian length
//! prefix followed by JSON.
//!
//! Duplicated from the server repo rather than shared as a crate, by choice —
//! the two projects stay independently versioned and releasable. The format is
//! small and frozen; the tests below pin it on this side too.

use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

use anyhow::{anyhow, Result};
use serde::Deserialize;

const HEADER: usize = 4;
const MAX_MESSAGE: usize = 1024 * 1024;

#[derive(Debug, Clone, Deserialize)]
pub struct Utterance {
    #[serde(default)]
    pub ts: Option<String>,
    #[serde(default)]
    pub text: String,
}

pub struct Client {
    socket: std::path::PathBuf,
    uid: String,
}

impl Client {
    pub fn new(socket: &Path, uid: &str) -> Self {
        Self { socket: socket.to_path_buf(), uid: uid.to_string() }
    }

    pub fn is_server_running(&self) -> bool {
        self.socket.exists()
    }

    fn connect(&self) -> Result<UnixStream> {
        if !self.socket.exists() {
            return Err(anyhow!("server socket not found: {}", self.socket.display()));
        }
        let stream = UnixStream::connect(&self.socket)?;
        // A hung server must not wedge the poll loop.
        stream.set_read_timeout(Some(Duration::from_secs(2)))?;
        stream.set_write_timeout(Some(Duration::from_secs(2)))?;
        Ok(stream)
    }

    fn round_trip(&self, request: &serde_json::Value) -> Result<serde_json::Value> {
        let mut stream = self.connect()?;
        let payload = serde_json::to_vec(request)?;
        stream.write_all(&(payload.len() as u32).to_be_bytes())?;
        stream.write_all(&payload)?;
        stream.flush()?;

        let mut header = [0u8; HEADER];
        read_exact(&mut stream, &mut header)?;
        let len = u32::from_be_bytes(header) as usize;
        if len > MAX_MESSAGE {
            return Err(anyhow!("response too large: {len} bytes"));
        }
        let mut body = vec![0u8; len];
        read_exact(&mut stream, &mut body)?;
        Ok(serde_json::from_slice(&body)?)
    }

    /// Discard anything transcribed before now.
    pub fn set_read_marker(&self) -> Result<()> {
        let response = self.round_trip(&serde_json::json!({
            "command": "set", "uid": self.uid,
        }))?;
        expect_ok(&response)?;
        Ok(())
    }

    /// Utterances since this client's marker.
    pub fn get_transcriptions(&self) -> Result<Vec<Utterance>> {
        let response = self.round_trip(&serde_json::json!({
            "command": "get", "uid": self.uid,
        }))?;
        expect_ok(&response)?;
        let text = response.get("text").and_then(|v| v.as_str()).unwrap_or("");
        Ok(text
            .lines()
            .filter(|l| !l.trim().is_empty())
            .filter_map(|line| match serde_json::from_str::<Utterance>(line) {
                Ok(u) => Some(u),
                Err(e) => {
                    tracing::warn!("ignoring malformed utterance line: {e}");
                    None
                }
            })
            .collect())
    }
}

fn expect_ok(response: &serde_json::Value) -> Result<()> {
    if response.get("status").and_then(|v| v.as_str()) == Some("ok") {
        return Ok(());
    }
    Err(anyhow!(
        "server error: {}",
        response
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
    ))
}

fn read_exact(stream: &mut impl Read, buf: &mut [u8]) -> Result<()> {
    let mut filled = 0;
    while filled < buf.len() {
        match stream.read(&mut buf[filled..]) {
            Ok(0) => return Err(anyhow!("server closed the connection")),
            Ok(n) => filled += n,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}
