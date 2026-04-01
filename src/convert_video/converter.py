import os
import fcntl
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from typing import Optional

from tqdm import tqdm

from convert_video.output import (
    info, warning, error, success, skip,
)
from convert_video.mediainfo import get_resolution, get_audio_info

# Global references for cleanup on signal
_current_temp_file: Optional[str] = None
_current_process: Optional[subprocess.Popen] = None
_interrupted = False
_last_sigint_time: float = 0.0
_DOUBLE_PRESS_INTERVAL = 1.5  # seconds


def _get_terminal_size() -> tuple[int, int]:
    """Return terminal rows and columns, falling back to a sensible default."""
    size = shutil.get_terminal_size(fallback=(80, 24))
    return size.lines, size.columns


def _set_pty_window_size(fd: int):
    """Apply the current terminal size to a PTY file descriptor."""
    rows, cols = _get_terminal_size()
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def handle_sigint(signum, frame):
    """Handle Ctrl+C: single press skips current file, double press exits."""
    global _interrupted, _last_sigint_time
    now = time.time()

    if now - _last_sigint_time < _DOUBLE_PRESS_INTERVAL:
        # Double Ctrl+C — abort everything
        print()
        error("Double Ctrl+C detected. Aborting all conversions...")
        if _current_process:
            try:
                _current_process.kill()
                _current_process.wait()
            except Exception:
                pass
        if _current_temp_file and os.path.exists(_current_temp_file):
            os.remove(_current_temp_file)
        os._exit(1)

    # Single Ctrl+C — skip current file
    _last_sigint_time = now
    _interrupted = True
    print()
    warning("Ctrl+C: skipping current file (press again quickly to abort all)...")
    if _current_process:
        try:
            _current_process.kill()
        except Exception:
            pass


def install_signal_handlers():
    """Register SIGINT/SIGTERM handlers for safe conversion interruption."""
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)


def generate_unique_filename(base_name: str, extension: str, output_path: str) -> str:
    counter = 1
    output_file = os.path.join(output_path, f"{base_name}.{extension}")
    while os.path.exists(output_file):
        match = re.search(r"\((\d+)\)$", base_name)
        if match:
            counter = int(match.group(1)) + 1
            base_name = base_name[:-len(match.group(0))]
        base_name += f" ({counter})"
        output_file = os.path.join(output_path, f"{base_name}.{extension}")
    return output_file


def preserve_audio_titles(input_file: str, output_file: str):
    """Copy audio track titles from input to output using mkvpropedit."""
    audio_tracks = get_audio_info(input_file)
    for i, track in enumerate(audio_tracks):
        title = track.get("Title", "Stereo")
        track_num = i + 1
        try:
            subprocess.run(
                ["mkvpropedit", output_file,
                 "--edit", f"track:a{track_num}",
                 "--set", f"name={title}"],
                capture_output=True, check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            warning(f"Could not set audio title for track {track_num}: {e}")


def confirm_prompt() -> bool:
    """Interactive confirmation prompt. Returns True to proceed, False to cancel."""
    while True:
        warning("Continue with transcoding? [Y(yes)/N(no)] (default Y): ")
        try:
            import tty
            import termios
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                key = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except (ImportError, termios.error, ValueError):
            # Fallback for non-TTY environments
            key = input().strip()
            if not key:
                key = "y"

        if key in ('\x1b',):  # Escape
            info("\nOperation cancelled by user (Escape).")
            return False
        elif key in ('', '\r', '\n', 'Y', 'y', 'S', 's'):
            print()
            return True
        elif key in ('N', 'n'):
            info("\nOperation cancelled.")
            return False
        else:
            print(f"\r\033[2K", end="")
            error("Invalid option. Try again.")
            time.sleep(0.7)
            print(f"\r\033[2K", end="")


def convert_video(input_file: str, output_dir: str, codec: str, encode_speed: str,
                   audio_passthrough: bool, verbose: bool,
                   title: int = None, resolution_override: str = None,
                   audio_tracks: list = None) -> bool:
    global _current_temp_file, _interrupted

    is_iso = title is not None

    if resolution_override:
        resolution = resolution_override
    else:
        resolution = get_resolution(input_file)
        if not resolution:
            return False

    # Build audio parameters
    audio_params = []
    if audio_passthrough:
        audio_params = [
            "--audio-lang-list", "all",
            "--all-audio",
            "--audio-copy-mask", "eac3,ac3,aac,truehd,dts,dtshd,mp2,mp3,opus,vorbis,flac,alac",
            "--aencoder", "copy",
            "--audio-fallback", "none",
        ]
    elif is_iso:
        # For ISO sources mediainfo cannot inspect tracks;
        # use audio info gathered during the scan to set per-track mixdown.
        from convert_video.iso import _channels_to_mixdown
        if audio_tracks:
            track_list = []
            encoder_list = []
            bitrate_list = []
            mixdown_list = []
            for at in audio_tracks:
                mix, br = _channels_to_mixdown(at['channels'])
                track_list.append(str(at['index']))
                encoder_list.append("opus")
                bitrate_list.append(str(br))
                mixdown_list.append(mix)
            audio_params = [
                "--audio", ",".join(track_list),
                "--aencoder", ",".join(encoder_list),
                "--ab", ",".join(bitrate_list),
                "--mixdown", ",".join(mixdown_list),
                "--audio-copy-mask", "",
            ]
        else:
            # Fallback: no track info available, encode all tracks
            audio_params = [
                "--audio-lang-list", "all",
                "--all-audio",
                "--aencoder", "opus",
                "--ab", "256",
                "--mixdown", "5point1",
                "--audio-copy-mask", "",
            ]
    else:
        audio_info = get_audio_info(input_file)
        if audio_info:
            track_list = []
            encoder_list = []
            bitrate_list = []
            mixdown_list = []
            for i, track in enumerate(audio_info):
                channels = int(track["Channels"])
                if channels == 2:
                    mix, br = "stereo", 128
                elif channels in [6, 7]:
                    mix, br = "5point1", 256
                elif channels == 8:
                    mix, br = "7point1", 320
                else:
                    mix, br = "dpl2", 160
                track_list.append(str(i + 1))
                encoder_list.append("opus")
                bitrate_list.append(str(br))
                mixdown_list.append(mix)
            audio_params = [
                "--audio", ",".join(track_list),
                "--aencoder", ",".join(encoder_list),
                "--ab", ",".join(bitrate_list),
                "--mixdown", ",".join(mixdown_list),
                "--audio-copy-mask", "",
            ]
        else:
            audio_params = [
                "--audio", "1",
                "--aencoder", "ac3",
                "--ab", "256",
                "--mixdown", "5point1",
                "--audio-copy-mask", "",
            ]

    # Determine output path and create temp file
    if output_dir:
        relative_path = os.path.relpath(input_file, os.getcwd())
        relative_dir = os.path.dirname(relative_path)
        output_subdir = os.path.join(output_dir, relative_dir)
    else:
        output_subdir = os.path.dirname(os.path.abspath(input_file))

    os.makedirs(output_subdir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    # HandBrakeCLI always outputs Matroska (-f mkv)
    extension = "mkv"

    if output_dir:
        final_output = generate_unique_filename(base_name, extension, output_subdir)
    else:
        final_output = generate_unique_filename(f"{base_name}_converted", extension, output_subdir)

    with tempfile.NamedTemporaryFile(
        suffix=f".{extension}", dir=output_subdir, prefix=f"{base_name}.tmp.", delete=False
    ) as tf:
        temp_filepath = tf.name
    _current_temp_file = temp_filepath

    # Build HandBrakeCLI command
    hb_params = [
        "HandBrakeCLI",
        "-i", input_file,
        "-o", temp_filepath,
        "--all-subtitles",
        "-f", "mkv",
    ]
    if title is not None:
        hb_params += ["--title", str(title)]
    hb_params += audio_params

    if encode_speed == "slow":
        hb_params.extend(["--preset", "H.265 MKV 2160p60 4K"])
    elif encode_speed == "normal":
        hb_params.extend(["--preset", "H.265 NVENC 2160p 4K"])
    elif encode_speed == "fast":
        hb_params.extend([
            "-e", codec,
            "-w", resolution.split("x")[0],
            "-l", resolution.split("x")[1],
            "-q", "30",
            "--vb", "1000",
        ])

    try:
        elapsed_text = None
        if verbose:
            # Verbose mode: show full HandBrakeCLI output
            _current_process = subprocess.Popen(hb_params)
            _current_process.wait()
            conversion_succeeded = _current_process.returncode == 0
            _current_process = None
        else:
            # Progress bar mode — use a pseudo-terminal so HandBrakeCLI
            # sees a real TTY and emits progress updates.
            conversion_succeeded = False
            master_fd, slave_fd = pty.openpty()
            _set_pty_window_size(slave_fd)
            print(f"Converting: {os.path.basename(input_file)}")
            with tqdm(
                total=100,
                dynamic_ncols=True,
                leave=False,
                bar_format="{percentage:3.0f}%|{bar}| [{elapsed}<{remaining}]",
            ) as pbar:
                process = subprocess.Popen(
                    hb_params,
                    stdout=slave_fd,
                    stderr=slave_fd,
                )
                os.close(slave_fd)
                _current_process = process

                def handle_resize(signum, frame):
                    """Redraw the progress bar and propagate window size changes."""
                    if process.poll() is not None:
                        return
                    try:
                        _set_pty_window_size(master_fd)
                    except OSError:
                        return
                    pbar.refresh()

                old_winch_handler = signal.getsignal(signal.SIGWINCH)
                signal.signal(signal.SIGWINCH, handle_resize)
                buf = b""
                try:
                    while True:
                        ready, _, _ = select.select([master_fd], [], [], 0.1)
                        if ready:
                            try:
                                chunk = os.read(master_fd, 4096)
                            except OSError:
                                break
                            if not chunk:
                                break
                            buf += chunk
                            # Process all complete lines (delimited by \r or \n)
                            while b"\r" in buf or b"\n" in buf:
                                idx_r = buf.find(b"\r")
                                idx_n = buf.find(b"\n")
                                if idx_r == -1:
                                    idx = idx_n
                                elif idx_n == -1:
                                    idx = idx_r
                                else:
                                    idx = min(idx_r, idx_n)
                                line = buf[:idx].decode("utf-8", errors="replace")
                                buf = buf[idx + 1:]
                                m = re.search(r"Encoding:.*? (\d+\.\d+) %", line)
                                if m:
                                    percent = float(m.group(1))
                                    increment = percent - pbar.n
                                    if increment > 0:
                                        pbar.update(increment)
                        elif process.poll() is not None:
                            # Drain remaining data after process exits
                            while True:
                                ready, _, _ = select.select([master_fd], [], [], 0.1)
                                if ready:
                                    try:
                                        chunk = os.read(master_fd, 4096)
                                    except OSError:
                                        break
                                    if not chunk:
                                        break
                                    buf += chunk
                                else:
                                    break
                            break
                finally:
                    signal.signal(signal.SIGWINCH, old_winch_handler)
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass
                process.wait()
                _current_process = None
                conversion_succeeded = process.returncode == 0
                elapsed_text = tqdm.format_interval(pbar.format_dict["elapsed"])

        # Check if this conversion was interrupted by Ctrl+C
        if _interrupted:
            _interrupted = False
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            _current_temp_file = None
            skip(f"Conversion skipped: {os.path.basename(input_file)}")
            return False

        if conversion_succeeded:
            shutil.move(temp_filepath, final_output)
            _current_temp_file = None
            if elapsed_text:
                success(f"Conversion successful [{elapsed_text}]")
            else:
                success(f"Conversion successful: {os.path.basename(final_output)}")
            # Preserve audio track titles from original file
            preserve_audio_titles(input_file, final_output)
            return True
        else:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            _current_temp_file = None
            if elapsed_text:
                error(f"Conversion failed [{elapsed_text}]: {os.path.basename(input_file)}")
            else:
                error(f"Conversion failed: {os.path.basename(input_file)}")
            return False
    except FileNotFoundError:
        error("HandBrakeCLI not found.")
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
        _current_temp_file = None
        return False
    except subprocess.CalledProcessError as e:
        error(f"Error during conversion: {e}")
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
        _current_temp_file = None
        return False


def poweroff_with_countdown():
    """Power off the system after a 10-second countdown, cancellable with Ctrl+C."""
    print("Powering off in 10 seconds (press Ctrl+C to cancel)... ", end="", flush=True)
    cancelled = False

    def cancel_handler(signum, frame):
        nonlocal cancelled
        cancelled = True

    old_handler = signal.signal(signal.SIGINT, cancel_handler)
    try:
        for count in range(10, 0, -1):
            if cancelled:
                break
            print(f"{count} ", end="", flush=True)
            time.sleep(1)
    finally:
        signal.signal(signal.SIGINT, old_handler)

    if cancelled:
        print(f"\r\033[2KPower off cancelled by user.")
    else:
        print("Powering off the system...")
        subprocess.run(["sudo", "systemctl", "poweroff"])
