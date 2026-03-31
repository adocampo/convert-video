#!/usr/bin/env python3
import argparse
import subprocess
import os
import json
import re
import shutil
import signal
import sys
import tempfile
import time
import glob
import pty
import select
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional
from tqdm import tqdm
from convert_video import get_version

# ANSI color codes
GREEN_COLOR = '\033[0;32m'
YELLOW_COLOR = '\033[1;33m'
RED_COLOR = '\033[0;31m'
RESET_COLOR = '\033[0m'
CYAN_COLOR = '\033[0;36m'

VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.ts')

# Codec quality hierarchy (higher = better compression)
CODEC_QUALITY = {
    'AVC': 1,     # h264
    'HEVC': 2,    # h265
    'AV1': 3,
}

# Map CLI codec names to mediainfo format names
CODEC_TO_FORMAT = {
    'nvenc_h264': 'AVC',
    'nvenc_h265': 'HEVC',
    'x265': 'HEVC',
    'av1': 'AV1',
}

# Global references for cleanup on signal
_current_temp_file: Optional[str] = None
_current_process: Optional[subprocess.Popen] = None
_interrupted = False
_last_sigint_time: float = 0.0
_DOUBLE_PRESS_INTERVAL = 1.5  # seconds


def handle_sigint(signum, frame):
    """Handle Ctrl+C: single press skips current file, double press exits."""
    global _interrupted, _last_sigint_time
    now = time.time()

    if now - _last_sigint_time < _DOUBLE_PRESS_INTERVAL:
        # Double Ctrl+C — abort everything
        print(f"\n{RED_COLOR}Double Ctrl+C detected. Aborting all conversions...{RESET_COLOR}")
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
    print(f"\n{YELLOW_COLOR}Ctrl+C: skipping current file (press again quickly to abort all)...{RESET_COLOR}")
    if _current_process:
        try:
            _current_process.kill()
        except Exception:
            pass


signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)


def info(msg: str):
    print(f"{GREEN_COLOR}{msg}{RESET_COLOR}")


def warning(msg: str):
    print(f"{YELLOW_COLOR}{msg}{RESET_COLOR}")


def error(msg: str):
    print(f"{RED_COLOR}{msg}{RESET_COLOR}", file=sys.stderr)


def get_thread_count() -> int:
    """Calculate 50% of available CPU threads, minimum 1."""
    total = os.cpu_count() or 2
    threads = total // 2
    return max(threads, 1)


def check_dependency(command: str):
    try:
        subprocess.run([command, '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        error(f"Error: {command} is required but not installed.")
        sys.exit(1)


def get_mediainfo_json(filepath: str) -> dict:
    """Get full mediainfo JSON output for a file."""
    try:
        result = subprocess.run(
            ["mediainfo", "--Output=JSON", filepath],
            capture_output=True, check=True, text=True,
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        error(f"Error getting media info for {filepath}: {e}")
        return {}


def get_resolution(filepath: str) -> str:
    try:
        result = subprocess.run(
            ["mediainfo", "--Inform=Video;%Width%x%Height%", filepath],
            capture_output=True, check=True, text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        error(f"Error getting resolution for {filepath}: {e}")
        return ""


def get_audio_info(filepath: str) -> List[dict]:
    data = get_mediainfo_json(filepath)
    if not data:
        return []
    try:
        return [t for t in data["media"]["track"] if t["@type"] == "Audio"]
    except (KeyError, TypeError):
        return []


def _format_duration(seconds_str: str) -> str:
    """Convert duration in seconds to HH:MM:SS format."""
    try:
        secs = float(seconds_str)
        hours = int(secs // 3600)
        mins = int((secs % 3600) // 60)
        remaining = int(secs % 60)
        return f"{hours:02d}:{mins:02d}:{remaining:02d}"
    except (ValueError, TypeError):
        return seconds_str


def _format_size(bytes_str: str) -> str:
    """Convert bytes to human-readable size."""
    try:
        size = int(bytes_str)
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"
    except (ValueError, TypeError):
        return bytes_str


def _format_bitrate(bitrate_str: str) -> str:
    """Convert bitrate in bps to human-readable format."""
    try:
        br = int(bitrate_str)
        if br >= 1_000_000:
            return f"{br / 1_000_000:.2f} Mbps"
        elif br >= 1_000:
            return f"{br / 1_000:.0f} kbps"
        return f"{br} bps"
    except (ValueError, TypeError):
        return bitrate_str


def show_source_info(filepath: str):
    """Display detailed technical information about a video file."""
    data = get_mediainfo_json(filepath)
    if not data:
        error(f"Could not read media info for {filepath}")
        return

    tracks = data.get("media", {}).get("track", [])

    # General info
    general = next((t for t in tracks if t["@type"] == "General"), None)
    if general:
        info("=== General ===")
        print(f"  Container:    {general.get('Format', 'N/A')} v{general.get('Format_Version', '?')}")
        if general.get('Title'):
            print(f"  Title:        {general['Title']}")
        duration = general.get('Duration', 'N/A')
        if duration != 'N/A':
            duration = _format_duration(duration)
        print(f"  Duration:     {duration}")
        print(f"  Size:         {_format_size(general.get('FileSize', 'N/A'))}")
        overall_br = general.get('OverallBitRate', 'N/A')
        if overall_br != 'N/A':
            print(f"  Bitrate:      {_format_bitrate(overall_br)}")
        if general.get('Encoded_Application'):
            print(f"  Muxer:        {general['Encoded_Application']}")
        if general.get('Encoded_Date'):
            print(f"  Encoded:      {general['Encoded_Date']}")
        print()

    # Video tracks
    video_tracks = [t for t in tracks if t["@type"] == "Video"]
    if video_tracks:
        for t in video_tracks:
            info(f"=== Video track {t.get('ID', '?')} ===")
            fmt = t.get('Format', 'N/A')
            profile = t.get('Format_Profile', '')
            level = t.get('Format_Level', '')
            fmt_full = fmt
            if profile:
                fmt_full += f"@{profile}"
            if level:
                fmt_full += f"@L{level}"
            print(f"  Format:       {fmt_full}")
            print(f"  Codec ID:     {t.get('CodecID', 'N/A')}")
            print(f"  Resolution:   {t.get('Width', '?')}x{t.get('Height', '?')}")
            dar = t.get('DisplayAspectRatio', '')
            if dar:
                print(f"  Aspect ratio: {dar}")
            fps = t.get('FrameRate', 'N/A')
            fps_mode = t.get('FrameRate_Mode', '')
            print(f"  Frame rate:   {fps} fps ({fps_mode})" if fps_mode else f"  Frame rate:   {fps} fps")
            br = t.get('BitRate', t.get('BitRate_Mode', 'N/A'))
            if br != 'N/A':
                print(f"  Bitrate:      {_format_bitrate(br)}")
            print(f"  Bit depth:    {t.get('BitDepth', 'N/A')}")
            print(f"  Chroma:       {t.get('ChromaSubsampling', 'N/A')}")
            print(f"  Scan type:    {t.get('ScanType', 'N/A')}")
            print(f"  Color space:  {t.get('ColorSpace', 'N/A')}")
            if t.get('Encoded_Library'):
                print(f"  Encoder:      {t['Encoded_Library']}")
            stream_size = t.get('StreamSize', '')
            if stream_size:
                print(f"  Stream size:  {_format_size(stream_size)}")
            print(f"  Default:      {t.get('Default', 'N/A')}")
            print(f"  Forced:       {t.get('Forced', 'N/A')}")
            print()

    # Audio tracks
    audio_tracks = [t for t in tracks if t["@type"] == "Audio"]
    if audio_tracks:
        for t in audio_tracks:
            info(f"=== Audio track {t.get('ID', '?')} ===")
            title = t.get('Title', '')
            if title:
                print(f"  Title:        {title}")
            fmt = t.get('Format', 'N/A')
            extra = t.get('Format_AdditionalFeatures', '')
            print(f"  Format:       {fmt} {extra}".rstrip())
            print(f"  Codec ID:     {t.get('CodecID', 'N/A')}")
            channels = t.get('Channels', '?')
            layout = t.get('ChannelLayout', '')
            positions = t.get('ChannelPositions', '')
            ch_info = f"{channels} ch"
            if layout:
                ch_info += f" ({layout})"
            elif positions:
                ch_info += f" ({positions})"
            print(f"  Channels:     {ch_info}")
            br = t.get('BitRate', t.get('BitRate_Mode', 'N/A'))
            if br != 'N/A':
                print(f"  Bitrate:      {_format_bitrate(br)}")
            print(f"  Sample rate:  {t.get('SamplingRate', 'N/A')} Hz")
            print(f"  Compression:  {t.get('Compression_Mode', 'N/A')}")
            stream_size = t.get('StreamSize', '')
            if stream_size:
                print(f"  Stream size:  {_format_size(stream_size)}")
            lang = t.get('Language', '')
            if lang:
                print(f"  Language:     {lang}")
            print(f"  Default:      {t.get('Default', 'N/A')}")
            print(f"  Forced:       {t.get('Forced', 'N/A')}")
            print()

    # Subtitle tracks
    text_tracks = [t for t in tracks if t["@type"] == "Text"]
    if text_tracks:
        for t in text_tracks:
            info(f"=== Subtitle track {t.get('ID', '?')} ===")
            title = t.get('Title', '')
            if title:
                print(f"  Title:        {title}")
            print(f"  Format:       {t.get('Format', 'N/A')}")
            print(f"  Codec ID:     {t.get('CodecID', 'N/A')}")
            lang = t.get('Language', '')
            if lang:
                print(f"  Language:     {lang}")
            print(f"  Default:      {t.get('Default', 'N/A')}")
            print(f"  Forced:       {t.get('Forced', 'N/A')}")
            print()
    elif not text_tracks:
        info("=== Subtitles ===")
        print("  No subtitle tracks found.")
        print()


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
                   audio_passthrough: bool, verbose: bool) -> bool:
    global _current_temp_file, _interrupted

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
    extension = os.path.splitext(input_file)[1][1:]

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
    ] + audio_params

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
        if verbose:
            # Verbose mode: show full HandBrakeCLI output
            _current_process = subprocess.Popen(hb_params)
            _current_process.wait()
            success = _current_process.returncode == 0
            _current_process = None
        else:
            # Progress bar mode — use a pseudo-terminal so HandBrakeCLI
            # sees a real TTY and emits progress updates.
            # Both stdout and stderr go through the PTY so isatty()
            # returns True for all fds HandBrakeCLI might check.
            success = False
            master_fd, slave_fd = pty.openpty()
            with tqdm(total=100, desc=f"Converting {os.path.basename(input_file)}", unit="%",
                      bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}% [{elapsed}<{remaining}]") as pbar:
                process = subprocess.Popen(
                    hb_params,
                    stdout=slave_fd,
                    stderr=slave_fd,
                )
                os.close(slave_fd)
                _current_process = process
                buf = b""
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
                try:
                    os.close(master_fd)
                except OSError:
                    pass
                process.wait()
                _current_process = None
                success = process.returncode == 0
                if not success and not _interrupted:
                    error("HandBrakeCLI returned an error.")

        # Check if this conversion was interrupted by Ctrl+C
        if _interrupted:
            _interrupted = False
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            _current_temp_file = None
            warning(f"Conversion skipped for: {os.path.basename(input_file)}")
            return False

        if success:
            shutil.move(temp_filepath, final_output)
            _current_temp_file = None
            print(f"\r\033[2K[{GREEN_COLOR}✓{RESET_COLOR}] Conversion successful: {final_output}")
            # Preserve audio track titles from original file
            preserve_audio_titles(input_file, final_output)
            return True
        else:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            _current_temp_file = None
            print(f"\r\033[2K[{RED_COLOR}✗{RESET_COLOR}] Conversion error")
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


def check_already_converted(input_file: str, target_codec: str, force: bool) -> str:
    """Check if a file is already in the target codec.
    Returns:
      'skip'    - already converted by HandBrake, skip it
      'warn'    - same codec but not HandBrake muxed, convert with warning
      'convert' - needs conversion
    """
    data = get_mediainfo_json(input_file)
    if not data:
        return 'convert'

    tracks = data.get('media', {}).get('track', [])
    general = next((t for t in tracks if t['@type'] == 'General'), None)
    video = next((t for t in tracks if t['@type'] == 'Video'), None)

    if not video or not general:
        return 'convert'

    current_format = video.get('Format', '').upper()
    target_format = CODEC_TO_FORMAT.get(target_codec, '').upper()

    if not target_format:
        return 'convert'

    current_quality = CODEC_QUALITY.get(current_format, 0)
    target_quality = CODEC_QUALITY.get(target_format, 0)

    # If current codec is worse than target, always convert
    if current_quality < target_quality:
        return 'convert'

    # If current codec is better than target, skip (don't downgrade)
    if current_quality > target_quality:
        basename = os.path.basename(input_file)
        info(f"[SKIP] '{basename}' is already in {current_format} which is better than {target_format}. Use --force to override.")
        return 'skip'

    # Same codec — check if it was muxed by HandBrake
    muxer = general.get('Encoded_Application', '')
    encoder = video.get('Encoded_Library_Name', '')

    is_handbrake = 'handbrake' in muxer.lower() or 'handbrake' in encoder.lower()

    if is_handbrake:
        basename = os.path.basename(input_file)
        info(f"[SKIP] '{basename}' is already {current_format} encoded by HandBrake. Use --force to override.")
        return 'skip'
    else:
        basename = os.path.basename(input_file)
        muxer_name = muxer or 'unknown'
        warning(f"[WARN] '{basename}' is already {current_format} but was muxed by '{muxer_name}'. Converting anyway.")
        return 'warn'


def find_video_files(pattern: str) -> List[str]:
    """Find video files recursively in directories matching a glob pattern (like --find in bash)."""
    cwd = os.getcwd()
    matched_dirs = []

    if pattern == "*":
        matched_dirs = [cwd]
    else:
        # Match directories under cwd that match the pattern
        search_pattern = os.path.join(cwd, pattern)
        for match in glob.glob(search_pattern):
            if os.path.isdir(match):
                matched_dirs.append(match)

    files = []
    for d in matched_dirs:
        for root, _, filenames in os.walk(d):
            for f in filenames:
                if f.lower().endswith(VIDEO_EXTENSIONS):
                    files.append(os.path.join(root, f))
    return files


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


GITHUB_REPO = "adocampo/convert-video"


def check_for_updates() -> tuple:
    """Query GitHub for the latest release and compare with local version.

    Returns (local_version, remote_version, update_available).
    """
    local_ver = get_version()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        error(f"Could not reach GitHub: {exc}")
        return local_ver, None, False

    remote_ver = data.get("tag_name", "").lstrip("v")
    if not remote_ver:
        error("Could not determine the latest remote version.")
        return local_ver, None, False

    update_available = remote_ver != local_ver
    return local_ver, remote_ver, update_available


def upgrade():
    """Upgrade convert-video to the latest version via pipx."""
    local_ver, remote_ver, update_available = check_for_updates()
    if remote_ver is None:
        sys.exit(1)

    print(f"  Current version : {local_ver}")
    print(f"  Latest version  : {remote_ver}")

    if not update_available:
        info("Already up to date.")
        sys.exit(0)

    print(f"\nUpgrading convert-video {local_ver} → {remote_ver} ...")
    result = subprocess.run(
        ["pipx", "install", f"git+https://github.com/{GITHUB_REPO}.git", "--force"],
        capture_output=False,
    )
    if result.returncode == 0:
        info(f"Successfully upgraded to {remote_ver}.")
    else:
        error("Upgrade failed. Check the output above for details.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Convert video files using HandBrakeCLI and preserve all audio and subtitle tracks."
    )
    parser.add_argument("input_files", nargs="*", default=[], help="Video files or directories to convert.")
    parser.add_argument("-o", "--output", default="", help="Output directory for converted files.")
    parser.add_argument("-c", "--codec", default="nvenc_h265",
                        help="Video codec: nvenc_h265 (default), nvenc_h264, av1, x265.")
    parser.add_argument("-s", "--slow", action="store_true", help="Use slow encoding speed.")
    parser.add_argument("-f", "--fast", action="store_true", help="Use fast encoding speed.")
    parser.add_argument("-n", "--normal", action="store_true", help="Use normal encoding speed (default).")
    parser.add_argument("-ap", "--audio-passthrough", action="store_true", help="Pass through original audio tracks.")
    parser.add_argument("-po", "--poweroff", action="store_true", help="Power off the system after conversion.")
    parser.add_argument("--find", nargs="?", const="*", default=None, metavar="PATTERN",
                        help="Recursively search for video files in directories matching the pattern, "
                             "or current directory if no pattern is given.")
    parser.add_argument("-y", "--yes", action="store_true", help="Automatically accept transcoding without prompts.")
    parser.add_argument("-si", "--source-info", action="store_true",
                        help="Show source information about a single video file.")
    parser.add_argument("--verbose", action="store_true", help="Show verbose output from HandBrakeCLI.")
    parser.add_argument("--force", action="store_true", help="Force conversion even if file is already in the target codec.")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Recursively search directories for video files matching the given patterns.")
    parser.add_argument("-v", "--version", action="version", version=f"convert-video {get_version()}")
    parser.add_argument("--update", action="store_true", help="Check if a newer version is available on GitHub.")
    parser.add_argument("--upgrade", action="store_true", help="Upgrade to the latest version from GitHub.")
    args = parser.parse_args()

    # Handle --update / --upgrade before dependency checks
    if args.update:
        local_ver, remote_ver, update_available = check_for_updates()
        print(f"  Current version : {local_ver}")
        if remote_ver:
            print(f"  Latest version  : {remote_ver}")
            if update_available:
                print(f"\n  Run 'convert-video --upgrade' to install the new version.")
            else:
                info("Already up to date.")
        sys.exit(0)

    if args.upgrade:
        upgrade()
        sys.exit(0)

    # Runtime dependency checks (only needed for actual conversion)
    check_dependency("HandBrakeCLI")
    check_dependency("mediainfo")
    check_dependency("mkvpropedit")

    threads = get_thread_count()
    print(f"Using {threads} threads for transcoding.")

    # Determine encoding speed
    if args.slow:
        speed = "slow"
    elif args.fast:
        speed = "fast"
    else:
        speed = "normal"

    # Handle --source-info: show info and exit
    if args.source_info:
        if not args.input_files:
            error("No input file provided for --source-info.")
            sys.exit(1)
        show_source_info(args.input_files[0])
        sys.exit(0)

    # Collect input files
    input_files = []
    if args.find is not None:
        input_files = find_video_files(args.find)
    else:
        for item in args.input_files:
            if os.path.isfile(item):
                if item.lower().endswith(VIDEO_EXTENSIONS):
                    input_files.append(item)
                else:
                    warning(f"Skipping non-video file: '{os.path.basename(item)}'")
            elif os.path.isdir(item):
                if args.recursive:
                    for root, _, filenames in os.walk(item):
                        for f in sorted(filenames):
                            if f.lower().endswith(VIDEO_EXTENSIONS):
                                input_files.append(os.path.join(root, f))
                else:
                    error(f"Directory '{item}' requires -r/--recursive option.")
                    sys.exit(1)
            else:
                # Try glob expansion (e.g. wildcards passed via noglob alias)
                matches = sorted(glob.glob(item))
                if not matches and args.recursive:
                    # Try recursive glob: convert pattern to **/pattern
                    base = os.path.dirname(item) or '.'
                    pattern = os.path.basename(item)
                    matches = sorted(glob.glob(os.path.join(base, '**', pattern), recursive=True))
                if matches:
                    for f in matches:
                        if os.path.isfile(f):
                            if f.lower().endswith(VIDEO_EXTENSIONS):
                                input_files.append(f)
                        elif os.path.isdir(f) and args.recursive:
                            for root, _, filenames in os.walk(f):
                                for fn in sorted(filenames):
                                    if fn.lower().endswith(VIDEO_EXTENSIONS):
                                        input_files.append(os.path.join(root, fn))
                        else:
                            warning(f"Not a file, skipping: '{f}'")
                else:
                    warning(f"No matches found for: '{item}'")

    if not input_files:
        error("No input files provided.")
        sys.exit(1)

    # Validate output directory
    if args.output:
        if not os.path.isdir(args.output):
            error(f"Output directory '{args.output}' does not exist.")
            sys.exit(1)
        if not os.access(args.output, os.W_OK):
            error(f"No write permission in output directory '{args.output}'.")
            sys.exit(1)

    # Display matching files
    print("Matching files:")
    for f in input_files:
        print(f"  {f}")

    # Confirmation prompt
    if not args.yes:
        if not confirm_prompt():
            sys.exit(0)

    # Start transcoding
    print("Starting transcoding...")

    skipped = 0
    for input_file in input_files:
        if not args.force:
            status = check_already_converted(input_file, args.codec, args.force)
            if status == 'skip':
                skipped += 1
                continue
            # 'warn' and 'convert' both proceed to conversion

        if not convert_video(input_file, args.output, args.codec, speed, args.audio_passthrough, args.verbose):
            warning(f"Conversion failed for: {input_file}")

    if skipped:
        info(f"\n{skipped} file(s) skipped (already converted).")


    print("Process complete.")

    # Power off if requested
    if args.poweroff:
        poweroff_with_countdown()


if __name__ == "__main__":
    main()
