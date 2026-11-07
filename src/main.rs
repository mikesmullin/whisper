//! whisper - voice keyboard via perception-voice.

use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use anyhow::{anyhow, Result};
use whisper::{app::App, config::Config};

const USAGE: &str = "\
whisper - voice keyboard via perception-voice

USAGE:
    whisper [-c CONFIG] [-v]

OPTIONS:
    -c, --config FILE   config file (default: ./config.yaml, then ~/.whisper.yaml)
    -v, --verbose       debug-level logging
    -h, --help          this message
";

fn main() -> Result<()> {
    let mut config_path: Option<PathBuf> = None;
    let mut verbose = false;

    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "-h" | "--help" => {
                print!("{USAGE}");
                return Ok(());
            }
            "-v" | "--verbose" => verbose = true,
            "-c" | "--config" => {
                i += 1;
                config_path = Some(PathBuf::from(
                    args.get(i).ok_or_else(|| anyhow!("--config needs a path"))?,
                ));
            }
            other => return Err(anyhow!("unexpected argument: {other}")),
        }
        i += 1;
    }

    let config = Config::load(config_path.as_deref())?;
    let default = if verbose || config.logging.verbose { "debug" } else { "info" };
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new(default)),
        )
        .with_target(false)
        .init();

    println!("{}", "=".repeat(60));
    println!("whisper v3 - Voice Keyboard (Rust)");
    println!("{}", "=".repeat(60));

    let stop = Arc::new(AtomicBool::new(false));
    for sig in [signal_hook::consts::SIGTERM, signal_hook::consts::SIGINT] {
        signal_hook::flag::register(sig, stop.clone())?;
    }

    let mut app = App::new(config)?;
    app.run(stop)
}
