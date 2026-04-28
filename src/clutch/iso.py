import os
import re
import subprocess
from typing import List, Optional, Tuple

from clutch import get_binary_path
from clutch.output import info, warning, error

ISO_EXTENSIONS = ('.iso',)


def _channels_to_mixdown(channels: float) -> Tuple[str, int]:
    """Map a channel count to a HandBrake mixdown name and opus bitrate."""
    if channels <= 2.0:
        return "stereo", 128
    elif channels <= 6.1:
        return "5point1", 256
    else:
        return "7point1", 320


def is_iso_file(filepath: str) -> bool:
    """Check if a file is an ISO disc image."""
    return filepath.lower().endswith(ISO_EXTENSIONS)


def scan_iso(filepath: str) -> List[dict]:
    """Scan an ISO image with HandBrakeCLI and return title information.

    Returns a list of dicts with keys:
      index, duration_seconds, duration_str, resolution
    """
    info(f"Scanning ISO image: {os.path.basename(filepath)} ...")
    try:
        result = subprocess.run(
            [get_binary_path("HandBrakeCLI"), "-i", filepath, "-t", "0", "--scan"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=300,
        )
        # HandBrakeCLI outputs scan info on stderr
        output = result.stderr
    except subprocess.TimeoutExpired:
        error(f"Timeout scanning ISO: {filepath}")
        return []
    except FileNotFoundError:
        error("HandBrakeCLI not found.")
        return []

    return _parse_scan_output(output)


def _parse_scan_output(output: str) -> List[dict]:
    """Parse HandBrakeCLI scan output to extract title information."""
    titles = []
    current_title = None
    in_audio_section = False

    for line in output.split('\n'):
        # Match title header: "+ title 1:" or "+ title 12:"
        title_match = re.match(r'.*\+ title (\d+):', line)
        if title_match:
            if current_title:
                titles.append(current_title)
            current_title = {
                'index': int(title_match.group(1)),
                'duration_seconds': 0,
                'duration_str': '00:00:00',
                'resolution': '',
                'audio_tracks': [],
            }
            in_audio_section = False
            continue

        if current_title is None:
            continue

        # Match duration: "  + duration: 02:15:30"
        dur_match = re.search(r'\+ duration: (\d+):(\d+):(\d+)', line)
        if dur_match:
            h = int(dur_match.group(1))
            m = int(dur_match.group(2))
            s = int(dur_match.group(3))
            current_title['duration_seconds'] = h * 3600 + m * 60 + s
            current_title['duration_str'] = f"{h:02d}:{m:02d}:{s:02d}"
            in_audio_section = False
            continue

        # Match size: "  + size: 1920x1080, ..."
        size_match = re.search(r'\+ size: (\d+x\d+)', line)
        if size_match:
            current_title['resolution'] = size_match.group(1)
            in_audio_section = False
            continue

        # Detect audio tracks section
        if re.search(r'\+ audio tracks:', line):
            in_audio_section = True
            continue

        # Detect end of audio section (another section starts)
        if in_audio_section and re.search(r'\+ (subtitle|duration|size|vts|autocrop|pixel|display|chapters)', line):
            in_audio_section = False
            # Don't skip, let other matchers handle it

        # Parse audio track: "  + 1, English (AC3) (5.1 ch) (192 kbps)"
        if in_audio_section:
            audio_match = re.search(
                r'\+ (\d+), ([^(]+?)\s*\(([^)]+)\)\s*\(([\d.]+) ch\)',
                line,
            )
            if audio_match:
                channels_str = audio_match.group(4)
                try:
                    channels = float(channels_str)
                except ValueError:
                    channels = 2.0
                current_title['audio_tracks'].append({
                    'index': int(audio_match.group(1)),
                    'language': audio_match.group(2).strip(),
                    'codec': audio_match.group(3).strip(),
                    'channels': channels,
                })
                continue

    # Don't forget the last title
    if current_title:
        titles.append(current_title)

    return titles


def select_main_title(titles: List[dict]) -> Optional[dict]:
    """Select the main title (longest duration) from a list of titles."""
    if not titles:
        return None
    return max(titles, key=lambda t: t['duration_seconds'])


def display_titles(titles: List[dict], selected_index: int):
    """Display all found titles, highlighting the selected one."""
    info(f"Found {len(titles)} title(s) in ISO image:")
    for t in titles:
        marker = f"  ◀ main title" if t['index'] == selected_index else ""
        print(f"  Title {t['index']:>2}: {t['duration_str']}  {t['resolution']}{marker}")
    print()
