import json
import os
import subprocess
from typing import List

from convert_video.output import info, warning, error, skip

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
        if not quiet:
            basename = os.path.basename(input_file)
            skip(f"'{basename}' is already in {current_format} which is better than {target_format}. Use --force to override.")
        return 'skip'

    # Same codec — check if it was muxed by HandBrake
    muxer = general.get('Encoded_Application', '')
    encoder = video.get('Encoded_Library_Name', '')

    is_handbrake = 'handbrake' in muxer.lower() or 'handbrake' in encoder.lower()

    if is_handbrake:
        if not quiet:
            basename = os.path.basename(input_file)
            skip(f"'{basename}' is already {current_format} encoded by HandBrake. Use --force to override.")
        return 'skip'
    else:
        if not quiet:
            basename = os.path.basename(input_file)
            muxer_name = muxer or 'unknown'
            warning(f"'{basename}' is already {current_format} but was muxed by '{muxer_name}'. Converting anyway.")
        return 'warn'
