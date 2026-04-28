import json
import os
import re
import subprocess
from typing import List

from clutch import get_binary_path
from clutch.output import info, warning, error, skip

VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.ts', '.iso')

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


def _collect_encoding_markers(*tracks: dict | None) -> list[str]:
    markers: list[str] = []
    seen: set[str] = set()

    for track in tracks:
        if not isinstance(track, dict):
            continue
        for key, value in track.items():
            if not isinstance(value, str):
                continue
            normalized_key = key.lower()
            if "encoded" not in normalized_key and "writing" not in normalized_key:
                continue
            marker = value.strip()
            if not marker:
                continue
            normalized_marker = marker.lower()
            if normalized_marker in seen:
                continue
            seen.add(normalized_marker)
            markers.append(marker)

    return markers


def _first_available_value(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def get_mediainfo_json(filepath: str) -> dict:
    """Get full mediainfo JSON output for a file."""
    try:
        result = subprocess.run(
            [get_binary_path("mediainfo"), "--Output=JSON", filepath],
            capture_output=True, check=True, encoding="utf-8", errors="replace",
        )
        if not result.stdout:
            stderr_msg = (result.stderr or "").strip()
            error(f"mediainfo returned no output for {filepath}"
                  + (f": {stderr_msg}" if stderr_msg else ""))
            return {}
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, TypeError,
            OSError) as e:
        error(f"Error getting media info for {filepath}: {e}")
        return {}


def get_media_duration_seconds(filepath: str) -> float:
    """Return the duration in seconds of a media file, or 0.0 if unknown."""
    data = get_mediainfo_json(filepath)
    if not data:
        return 0.0
    tracks = (data.get("media") or {}).get("track") or []
    general = next((t for t in tracks if t.get("@type") == "General"), None)
    if not general:
        return 0.0
    try:
        return float(general.get("Duration", 0))
    except (TypeError, ValueError):
        return 0.0


def extract_media_summary(filepath: str) -> dict:
    """Extract a compact media summary suitable for storing in job metadata."""
    data = get_mediainfo_json(filepath)
    if not data:
        return {}
    tracks = (data.get("media") or {}).get("track") or []

    general = next((t for t in tracks if t.get("@type") == "General"), None)
    summary: dict = {}
    if general:
        summary["container"] = general.get("Format", "")
        duration = general.get("Duration", "")
        if duration:
            summary["duration"] = _format_duration(duration)
        bitrate = general.get("OverallBitRate", "")
        if bitrate:
            summary["bitrate"] = _format_bitrate(bitrate)

    video_tracks = [t for t in tracks if t.get("@type") == "Video"]
    if video_tracks:
        vids = []
        for t in video_tracks:
            fmt = t.get("Format", "")
            profile = t.get("Format_Profile", "")
            entry: dict = {
                "codec": f"{fmt}@{profile}" if profile else fmt,
                "resolution": f"{t.get('Width', '?')}x{t.get('Height', '?')}",
            }
            fps = t.get("FrameRate", "")
            if fps:
                entry["fps"] = fps
            br = t.get("BitRate", "")
            if br:
                entry["bitrate"] = _format_bitrate(br)
            depth = t.get("BitDepth", "")
            if depth:
                entry["bit_depth"] = depth
            vids.append(entry)
        summary["video"] = vids

    audio_tracks = [t for t in tracks if t.get("@type") == "Audio"]
    if audio_tracks:
        auds = []
        for t in audio_tracks:
            entry = {"codec": t.get("Format", "")}
            channels = t.get("Channels", "")
            layout = t.get("ChannelLayout", "")
            if channels:
                entry["channels"] = f"{channels} ch" + (f" ({layout})" if layout else "")
            lang = t.get("Language", "")
            if lang:
                entry["lang"] = lang
            br = t.get("BitRate", "")
            if br:
                entry["bitrate"] = _format_bitrate(br)
            title = t.get("Title", "")
            if title:
                entry["title"] = title
            auds.append(entry)
        summary["audio"] = auds

    text_tracks = [t for t in tracks if t.get("@type") == "Text"]
    if text_tracks:
        subs = []
        for t in text_tracks:
            entry = {"codec": t.get("Format", "")}
            lang = t.get("Language", "")
            if lang:
                entry["lang"] = lang
            title = t.get("Title", "")
            if title:
                entry["title"] = title
            forced = t.get("Forced", "")
            if forced and forced.lower() == "yes":
                entry["forced"] = True
            subs.append(entry)
        summary["subtitles"] = subs

    return summary


def get_resolution(filepath: str) -> str:
    try:
        result = subprocess.run(
            [get_binary_path("mediainfo"), "--Inform=Video;%Width%x%Height%", filepath],
            capture_output=True, check=True, encoding="utf-8", errors="replace",
        )
        res = (result.stdout or "").strip()
        if res:
            return res
    except (subprocess.CalledProcessError, OSError) as e:
        error(f"Error getting resolution for {filepath}: {e}")

    # Fallback: try HandBrakeCLI scan when mediainfo fails
    try:
        scan = subprocess.run(
            [get_binary_path("HandBrakeCLI"), "-i", filepath, "-t", "1", "--scan"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=120,
        )
        m = re.search(r'\+ size: (\d+x\d+)', scan.stderr or "")
        if m:
            warning(f"Resolution for {os.path.basename(filepath)} obtained via HandBrakeCLI scan fallback")
            return m.group(1)
    except (subprocess.TimeoutExpired, OSError) as e:
        error(f"HandBrakeCLI scan fallback also failed for {filepath}: {e}")
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
        muxer_name = _first_available_value(
            general.get('Encoded_Application', ''),
            general.get('Writing_Application', ''),
            general.get('Encoded_Library', ''),
            general.get('Encoded_Library_Name', ''),
        )
        if muxer_name:
            print(f"  Muxer:        {muxer_name}")
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
            encoder_name = _first_available_value(
                t.get('Encoded_Library', ''),
                t.get('Encoded_Library_Name', ''),
                t.get('Writing_library', ''),
                t.get('Writing_Library', ''),
            )
            if encoder_name:
                print(f"  Encoder:      {encoder_name}")
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


def check_already_converted(input_file: str, target_codec: str, force: bool, quiet: bool = False) -> str:
    """Check if a file is already in the target codec.

    Returns:
      'skip'    - already converted by HandBrake, skip it
      'warn'    - same codec but not HandBrake muxed, convert with warning
      'convert' - needs conversion
    """
    data = get_mediainfo_json(input_file)
    if not data:
        return 'convert'

    if force:
        return 'convert'

    tracks = (data.get('media') or {}).get('track', [])
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
        if not quiet:
            basename = os.path.basename(input_file)
            skip(f"'{basename}' is already in {current_format} which is better than {target_format}. Use --force to override.")
        return 'skip'

    # Same codec — check if it was encoded or muxed by HandBrake.
    encoding_markers = _collect_encoding_markers(general, video)
    is_handbrake = any('handbrake' in marker.lower() for marker in encoding_markers)

    if is_handbrake:
        if not quiet:
            basename = os.path.basename(input_file)
            skip(f"'{basename}' is already {current_format} encoded by HandBrake. Use --force to override.")
        return 'skip'
    else:
        if not quiet:
            basename = os.path.basename(input_file)
            muxer_name = _first_available_value(
                general.get('Encoded_Application', ''),
                general.get('Writing_Application', ''),
                general.get('Encoded_Library', ''),
                general.get('Encoded_Library_Name', ''),
                video.get('Encoded_Library', ''),
                video.get('Encoded_Library_Name', ''),
                video.get('Writing_library', ''),
                video.get('Writing_Library', ''),
            ) or 'unknown'
            warning(f"'{basename}' is already {current_format} but was muxed by '{muxer_name}'. Converting anyway.")
        return 'warn'
