//! Example: Windows screen capture (ddagrab) -> VP9 (libvpx) encode -> TCP,
//! demonstrating the -idr_control_socket feature added by
//! patches/idr-control-socket.patch.
//!
//! This process is the TCP *server* (listener); the `ffmpeg` CLI is spawned
//! as a child process acting as the TCP *client*, streaming an MPEG-TS
//! payload into us. Every IDR_INTERVAL, we connect to ffmpeg's IDR control
//! socket/pipe and send a "force_idr" request, independent of the encoder's
//! own GOP interval (-g), and write everything we receive to `out.ts`.
//!
//! ffmpeg itself is not built by this example -- it must already be on
//! PATH (built from this repo, with libvpx_vp9 and -idr_control_socket
//! support, i.e. after applying patches/idr-control-socket.patch).

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

const TCP_PORT: u16 = 47890;
const OUTPUT_FILE: &str = "out.ts";
const IDR_INTERVAL: Duration = Duration::from_secs(5);

#[cfg(windows)]
const IDR_CONTROL_PATH: &str = r"\\.\pipe\ddagrab_vp9_tcp_idr";
#[cfg(not(windows))]
const IDR_CONTROL_PATH: &str = "/tmp/ddagrab_vp9_tcp_idr.sock";

fn spawn_ffmpeg() -> std::io::Result<Child> {
    // ddagrab is a Windows-only avdevice indev (DXGI Desktop Duplication).
    // On other platforms substitute e.g. `-f avfoundation -i 1:none` (macOS)
    // or `-f xcbgrab -i :0.0` (Linux) -- the -idr_control_socket /
    // -c:v libvpx_vp9 portion of this command line is platform-independent.
    #[cfg(windows)]
    let input_args: &[&str] = &["-f", "ddagrab", "-i", "desktop"];
    #[cfg(target_os = "macos")]
    let input_args: &[&str] = &["-f", "avfoundation", "-i", "1:none"];
    #[cfg(all(unix, not(target_os = "macos")))]
    let input_args: &[&str] = &["-f", "xcbgrab", "-i", ":0.0"];

    let mut cmd = Command::new("ffmpeg");
    cmd.args(input_args)
        .args(["-idr_control_socket", IDR_CONTROL_PATH])
        .args(["-c:v", "libvpx_vp9", "-b:v", "2M", "-g", "300"])
        .args(["-f", "mpegts", &format!("tcp://127.0.0.1:{TCP_PORT}")])
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    cmd.spawn()
}

/// Connects to ffmpeg's IDR control socket/pipe and sends one "force_idr"
/// request, then disconnects. ffmpeg's listener accepts a fresh connection
/// per request (see fftools/ffmpeg_idr_control.c), so no persistent
/// connection is kept open here.
fn send_force_idr() {
    #[cfg(windows)]
    {
        use std::fs::OpenOptions;
        match OpenOptions::new().write(true).open(IDR_CONTROL_PATH) {
            Ok(mut pipe) => {
                if let Err(e) = pipe.write_all(b"force_idr\n") {
                    eprintln!("[idr] failed to write to named pipe: {e}");
                } else {
                    println!("[idr] sent force_idr");
                }
            }
            Err(e) => eprintln!("[idr] failed to connect to named pipe {IDR_CONTROL_PATH}: {e}"),
        }
    }
    #[cfg(not(windows))]
    {
        use std::os::unix::net::UnixStream;
        match UnixStream::connect(IDR_CONTROL_PATH) {
            Ok(mut sock) => {
                if let Err(e) = sock.write_all(b"force_idr\n") {
                    eprintln!("[idr] failed to write to unix socket: {e}");
                } else {
                    println!("[idr] sent force_idr");
                }
            }
            Err(e) => eprintln!("[idr] failed to connect to unix socket {IDR_CONTROL_PATH}: {e}"),
        }
    }
}

fn handle_connection(mut stream: TcpStream, running: Arc<AtomicBool>) -> std::io::Result<()> {
    let mut out = std::fs::File::create(OUTPUT_FILE)?;
    let mut buf = [0u8; 64 * 1024];

    stream.set_read_timeout(Some(Duration::from_millis(500)))?;

    println!("[tcp] client connected, writing to {OUTPUT_FILE}");

    while running.load(Ordering::SeqCst) {
        match stream.read(&mut buf) {
            Ok(0) => break, // ffmpeg closed the connection
            Ok(n) => out.write_all(&buf[..n])?,
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => continue,
            Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut => continue,
            Err(e) => return Err(e),
        }
    }

    println!("[tcp] connection closed");
    Ok(())
}

fn main() -> std::io::Result<()> {
    let running = Arc::new(AtomicBool::new(true));
    {
        let running = Arc::clone(&running);
        ctrlc::set_handler(move || {
            println!("\nCtrl+C received, shutting down...");
            running.store(false, Ordering::SeqCst);
        })
        .expect("failed to set Ctrl+C handler");
    }

    let listener = TcpListener::bind(("127.0.0.1", TCP_PORT))?;
    println!("[tcp] listening on 127.0.0.1:{TCP_PORT}");

    let mut ffmpeg = spawn_ffmpeg()?;
    println!("[ffmpeg] spawned (pid {})", ffmpeg.id());

    // Periodically force an IDR on the ffmpeg encoder, independent of its
    // own -g 300 GOP interval, to demonstrate -idr_control_socket.
    {
        let running = Arc::clone(&running);
        thread::spawn(move || {
            // Give ffmpeg a moment to start its -idr_control_socket listener
            // before the first request.
            thread::sleep(Duration::from_secs(2));
            while running.load(Ordering::SeqCst) {
                send_force_idr();
                thread::sleep(IDR_INTERVAL);
            }
        });
    }

    listener.set_nonblocking(true)?;
    let mut handled = false;
    while running.load(Ordering::SeqCst) && !handled {
        match listener.accept() {
            Ok((stream, addr)) => {
                println!("[tcp] accepted connection from {addr}");
                handle_connection(stream, Arc::clone(&running))?;
                handled = true;
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(200));
            }
            Err(e) => return Err(e),
        }
    }

    println!("[ffmpeg] terminating child process...");
    let _ = ffmpeg.kill();
    let _ = ffmpeg.wait();

    println!("Done. Output written to {OUTPUT_FILE}");
    Ok(())
}
