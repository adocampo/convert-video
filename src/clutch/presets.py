"""Preset management: HandBrake official preset discovery and custom preset schema.

A *custom preset* is a JSON document with this shape::

    {
        "handbrake_preset": "H.265 NVENC 2160p 4K",  # optional base official preset
        "video": {
            "encoder": "x265|x264|nvenc_h265|nvenc_h264|av1|av1_nvenc|vp9|...",
            "quality_mode": "crf|abr",
            "quality_value": 22,            # CRF (lower = better) or kbps when abr
            "encoder_preset": "slow|medium|fast|p1..p7|...",
            "max_width": 0,                 # 0 = keep source resolution
            "max_height": 0,
            "framerate_mode": "same-as-source|peak|constant",
            "framerate_value": 0,           # fps when peak/constant, 0 = source
            "extra_options": "",            # freeform passed to --encopts
        },
        "audio": {
            "mode": "passthrough|encode|copy_with_fallback",
            "encoder": "opus|aac|ac3|eac3",
            "bitrate": 0,                   # 0 = auto / per-channel default
            "mixdown": "auto|stereo|5point1|7point1|dpl2",
        },
        "container": {
            "format": "mkv|mp4",
            "chapter_markers": true
        },
        "subtitles": {
            "mode": "all|none|first"
        },
        "filters": {
            "deinterlace": "off|default|skip-spatial|bob",
            "denoise": "off|light|medium|strong"
        }
    }

The fields are intentionally curated. ``handbrake_preset`` is optional; when
set, HandBrake's official preset is used as the base and the ``video``/``audio``
fields override it (only fields with non-default values are emitted as CLI args).
When ``handbrake_preset`` is empty, the args are built from scratch.

Official presets are discovered at runtime by invoking
``HandBrakeCLI --preset-list --json`` (cached after first successful call).
"""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Dict, List, Optional

from clutch import get_binary_path
from clutch.output import debug, warning


# ---------------------------------------------------------------------------
# Curated preset schema defaults
# ---------------------------------------------------------------------------

DEFAULT_PRESET_PARAMS: Dict[str, Dict[str, object]] = {
    "handbrake_preset": "",
    "video": {
        "encoder": "nvenc_h265",
        "quality_mode": "crf",
        "quality_value": 22,
        "encoder_preset": "",
        "max_width": 0,
        "max_height": 0,
        "framerate_mode": "same-as-source",
        "framerate_value": 0,
        "extra_options": "",
    },
    "audio": {
        "mode": "encode",
        "encoder": "opus",
        "bitrate": 0,
        "mixdown": "auto",
    },
    "container": {
        "format": "mkv",
        "chapter_markers": True,
    },
    "subtitles": {
        "mode": "all",
    },
    "filters": {
        "deinterlace": "off",
        "denoise": "off",
    },
}


# Allowed string values for select-type fields. Used by validation.
ALLOWED_VALUES: Dict[str, set] = {
    "video.encoder": {
        "x264", "x265", "x265_10bit", "nvenc_h264", "nvenc_h265", "nvenc_h265_10bit",
        "av1", "av1_nvenc", "av1_qsv", "vp9", "vp9_10bit", "qsv_h264", "qsv_h265",
        "vt_h264", "vt_h265", "mpeg2", "mpeg4", "theora",
    },
    "video.quality_mode": {"crf", "abr"},
    "video.framerate_mode": {"same-as-source", "peak", "constant"},
    "audio.mode": {"passthrough", "encode", "copy_with_fallback"},
    "audio.encoder": {"opus", "aac", "ac3", "eac3", "flac", "mp3"},
    "audio.mixdown": {"auto", "stereo", "5point1", "7point1", "dpl2", "mono"},
    "container.format": {"mkv", "mp4"},
    "subtitles.mode": {"all", "none", "first"},
    "filters.deinterlace": {"off", "default", "skip-spatial", "bob"},
    "filters.denoise": {"off", "light", "medium", "strong"},
}


def normalize_preset_params(params: Optional[Dict[str, object]]) -> Dict[str, object]:
    """Merge the provided params with the defaults and validate select fields.

    Unknown keys inside known sections are preserved (forward-compat); top-level
    unknown keys are dropped. Raises ValueError on invalid select values.
    """
    if not isinstance(params, dict):
        params = {}
    result: Dict[str, object] = {}
    result["handbrake_preset"] = str(params.get("handbrake_preset") or "").strip()

    for section, defaults in DEFAULT_PRESET_PARAMS.items():
        if section == "handbrake_preset":
            continue
        merged = dict(defaults)  # type: ignore[arg-type]
        provided = params.get(section)
        if isinstance(provided, dict):
            merged.update(provided)
        result[section] = merged

    # Validate select fields
    for path, allowed in ALLOWED_VALUES.items():
        section, field = path.split(".", 1)
        value = str(result.get(section, {}).get(field) or "")  # type: ignore[union-attr]
        if value and value not in allowed:
            raise ValueError(f"Invalid value for {path!r}: {value!r}")

    # Numeric coercion / clamping
    video = result["video"]
    for f in ("quality_value", "max_width", "max_height", "framerate_value"):
        try:
            video[f] = int(float(video.get(f) or 0))  # type: ignore[index]
        except (TypeError, ValueError):
            video[f] = 0
    audio = result["audio"]
    try:
        audio["bitrate"] = int(float(audio.get("bitrate") or 0))  # type: ignore[index]
    except (TypeError, ValueError):
        audio["bitrate"] = 0
    container = result["container"]
    container["chapter_markers"] = bool(container.get("chapter_markers", True))  # type: ignore[index]

    return result


# ---------------------------------------------------------------------------
# HandBrake official preset discovery
# ---------------------------------------------------------------------------

# Cached parsed output of `HandBrakeCLI --preset-list --json`. Key: binary path.
_official_cache: Dict[str, Dict[str, object]] = {}
_cache_lock = threading.Lock()


def _run_handbrake_preset_list(handbrake_path: str) -> str:
    """Invoke HandBrakeCLI to dump its built-in preset catalogue.

    First tries ``--preset-export-file /dev/stdout`` which outputs full JSON
    with all preset metadata. Falls back to ``--preset-list`` (plain text with
    names only) if the export fails.
    """
    import tempfile, os

    # Try exporting full preset JSON via a temp file (works on all platforms).
    tmpfd, tmppath = tempfile.mkstemp(suffix=".json", prefix="clutch_presets_")
    os.close(tmpfd)
    try:
        proc = subprocess.run(
            [handbrake_path, "--preset-export-file", tmppath],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode == 0 and os.path.getsize(tmppath) > 2:
            with open(tmppath, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip().startswith("{"):
                debug("Loaded official presets via --preset-export-file (full JSON).")
                return content
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            os.unlink(tmppath)
        except OSError:
            pass

    # Fallback: plain text listing (no encoder metadata).
    proc = subprocess.run(
        [handbrake_path, "--preset-list"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    # HandBrake writes the catalogue (and log lines) to stderr on most builds,
    # but some builds emit on stdout. Combine both to be safe.
    parts = []
    if proc.stdout:
        parts.append(proc.stdout)
    if proc.stderr:
        parts.append(proc.stderr)
    return "\n".join(parts)


# Matches HandBrake log lines like ``[15:23:12] hb_init: ...`` so we can skip them.
_LOG_LINE_PREFIX = "["


def _parse_preset_list_text(raw: str) -> List[Dict[str, object]]:
    """Parse HandBrakeCLI's plain-text ``--preset-list`` output into groups.

    The format is::

        Category/
            Preset Name
                Description, possibly wrapped
                onto multiple lines.
            Another Preset
                ...
        Another Category/
            ...

    Log lines (prefixed with ``[HH:MM:SS]``) are skipped. Returns the same
    shape as :func:`_walk_preset_tree`: a list of
    ``{"category": str, "presets": [...]}``.
    """
    groups: List[Dict[str, object]] = []
    current_category: Optional[str] = None
    current_presets: List[Dict[str, object]] = []
    current_preset: Optional[Dict[str, object]] = None
    desc_buffer: List[str] = []

    def flush_preset() -> None:
        nonlocal current_preset
        if current_preset is not None:
            if desc_buffer:
                current_preset["description"] = " ".join(
                    s.strip() for s in desc_buffer if s.strip()
                ).strip()
            current_presets.append(current_preset)
        current_preset = None
        desc_buffer.clear()

    def flush_category() -> None:
        flush_preset()
        if current_category and current_presets:
            groups.append({"category": current_category, "presets": list(current_presets)})
        current_presets.clear()

    for raw_line in raw.splitlines():
        # Strip trailing whitespace but preserve leading indentation.
        line = raw_line.rstrip()
        if not line:
            continue
        # Skip HandBrake log lines (``[HH:MM:SS] ...``).
        stripped = line.lstrip()
        if stripped.startswith(_LOG_LINE_PREFIX):
            continue
        # Stop at HandBrake's final shutdown line, which has no timestamp.
        if stripped.startswith("HandBrake has exited"):
            break

        indent = len(line) - len(stripped)

        if indent == 0 and stripped.endswith("/"):
            # Category header.
            flush_category()
            current_category = stripped[:-1].strip() or "Other"
        elif indent <= 4 and current_category is not None:
            # New preset entry (HandBrake uses 4-space indent).
            flush_preset()
            current_preset = {
                "name": stripped,
                "description": "",
                "video_encoder": "",
                "video_quality": None,
                "video_bitrate": None,
                "container": "",
                "audio_encoder": "",
            }
        elif current_preset is not None:
            # Continuation of a description (8-space indent or more).
            desc_buffer.append(stripped)

    flush_category()
    return groups


def _extract_preset_json(raw: str) -> Optional[Dict[str, object]]:
    """Extract the first valid top-level JSON object from raw output."""
    if not raw:
        return None
    # HandBrake may prepend log lines before the JSON. Find the first '{'.
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _summarize_preset(node: Dict[str, object]) -> Dict[str, object]:
    """Reduce a HandBrake preset entry to a small UI-friendly summary."""
    video_encoder = str(node.get("VideoEncoder") or "")
    return {
        "name": str(node.get("PresetName") or ""),
        "description": str(node.get("PresetDescription") or "").strip(),
        "video_encoder": video_encoder,
        "video_quality": node.get("VideoQualitySlider"),
        "video_bitrate": node.get("VideoAvgBitrate"),
        "container": str(node.get("FileFormat") or ""),
        "audio_encoder": ",".join(
            str(t.get("AudioEncoder") or "")
            for t in (node.get("AudioList") or [])
            if isinstance(t, dict)
        ),
    }


def _walk_preset_tree(tree: object) -> List[Dict[str, object]]:
    """Recursively flatten a HandBrake preset tree into category groups.

    HandBrake's JSON looks roughly like ``{"PresetList": [{"PresetName": "General",
    "ChildrenArray": [...] or "PresetList": [...]}]}``. Each leaf has
    ``"Type": 1`` (built-in preset). We return a flat list of
    ``{"category": "...", "presets": [{...}]}`` dicts.
    """
    groups: List[Dict[str, object]] = []

    def visit(category: str, items: object):
        if not isinstance(items, list):
            return
        leaves: List[Dict[str, object]] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            children = entry.get("ChildrenArray") or entry.get("PresetList")
            if children:
                # Nested folder — recurse with the entry's own name as category.
                visit(str(entry.get("PresetName") or category), children)
                continue
            if "PresetName" in entry:
                leaves.append(_summarize_preset(entry))
        if leaves:
            groups.append({"category": category, "presets": leaves})

    if isinstance(tree, dict):
        top = tree.get("PresetList") or tree.get("PresetsList") or tree
        if isinstance(top, list):
            for entry in top:
                if not isinstance(entry, dict):
                    continue
                children = entry.get("ChildrenArray") or entry.get("PresetList")
                if children:
                    visit(str(entry.get("PresetName") or "Other"), children)
                elif "PresetName" in entry:
                    visit("Other", [entry])
    elif isinstance(tree, list):
        visit("Other", tree)

    return groups


def list_official_presets(force_refresh: bool = False) -> Dict[str, object]:
    """Return the HandBrake built-in preset catalogue grouped by category.

    Result shape::

        {
            "available": True,
            "groups": [
                {"category": "General", "presets": [{...}, {...}]},
                ...
            ],
            "error": ""
        }

    If HandBrakeCLI is missing or its output cannot be parsed, ``available`` is
    False and ``error`` carries a human-readable hint. Result is cached per
    binary path; pass ``force_refresh=True`` to discard the cache.
    """
    try:
        binary = get_binary_path("HandBrakeCLI")
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "groups": [], "error": str(exc)}

    with _cache_lock:
        if not force_refresh and binary in _official_cache:
            return _official_cache[binary]

    try:
        raw = _run_handbrake_preset_list(binary)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        result = {"available": False, "groups": [], "error": f"HandBrakeCLI not available: {exc}"}
        with _cache_lock:
            _official_cache[binary] = result
        return result

    parsed = _extract_preset_json(raw)
    if parsed:
        groups = _walk_preset_tree(parsed)
    else:
        groups = _parse_preset_list_text(raw)

    if not groups:
        warning("Could not parse HandBrakeCLI --preset-list output.")
        result = {"available": False, "groups": [], "error": "Could not parse HandBrakeCLI preset list."}
        with _cache_lock:
            _official_cache[binary] = result
        return result

    debug(f"Discovered {sum(len(g['presets']) for g in groups)} HandBrake official presets.")
    result = {"available": True, "groups": groups, "error": ""}
    with _cache_lock:
        _official_cache[binary] = result
    return result


def find_official_preset(name: str) -> Optional[Dict[str, object]]:
    """Look up a single official preset summary by name (case-sensitive)."""
    if not name:
        return None
    catalogue = list_official_presets()
    for group in catalogue.get("groups", []):  # type: ignore[union-attr]
        for entry in group.get("presets", []):
            if str(entry.get("name") or "") == name:
                return entry
    return None


# ---------------------------------------------------------------------------
# HandBrake CLI argument generation from a normalized preset dict
# ---------------------------------------------------------------------------

# Map of curated audio mixdown values to HandBrake mixdown names.
_MIXDOWN_MAP = {
    "stereo": "stereo",
    "5point1": "5point1",
    "7point1": "7point1",
    "dpl2": "dpl2",
    "mono": "mono",
}

_DEINTERLACE_MAP = {
    "default": ["--deinterlace"],
    "skip-spatial": ["--deinterlace=skip-spatial"],
    "bob": ["--deinterlace=bob"],
}

_DENOISE_MAP = {
    "light": ["--nlmeans=light"],
    "medium": ["--nlmeans=medium"],
    "strong": ["--nlmeans=strong"],
}


def build_handbrake_args(preset: Dict[str, object], *, source_resolution: str = "") -> List[str]:
    """Return the HandBrake CLI argument list derived from a preset.

    If ``preset['handbrake_preset']`` is set, the official preset is used as
    base via ``--preset "Name"``; otherwise args are built from scratch.
    The returned list does NOT include the ``HandBrakeCLI``, ``-i``, ``-o`` or
    ``--all-subtitles`` flags — only the encoding-specific ones.
    """
    args: List[str] = []
    base_preset = str(preset.get("handbrake_preset") or "").strip()

    if base_preset:
        args.extend(["--preset", base_preset])

    video = preset.get("video") or {}
    if isinstance(video, dict):
        encoder = str(video.get("encoder") or "").strip()
        if encoder:
            args.extend(["-e", encoder])
        quality_mode = str(video.get("quality_mode") or "crf").strip()
        quality_value = video.get("quality_value")
        try:
            qv = float(quality_value) if quality_value is not None else None
        except (TypeError, ValueError):
            qv = None
        if qv is not None and qv > 0:
            if quality_mode == "abr":
                args.extend(["--vb", str(int(qv))])
            else:
                args.extend(["-q", str(qv)])
        encoder_preset = str(video.get("encoder_preset") or "").strip()
        if encoder_preset:
            args.extend(["--encoder-preset", encoder_preset])
        max_width = int(video.get("max_width") or 0)
        max_height = int(video.get("max_height") or 0)
        if max_width > 0:
            args.extend(["-w", str(max_width)])
        if max_height > 0:
            args.extend(["-l", str(max_height)])
        framerate_mode = str(video.get("framerate_mode") or "").strip()
        framerate_value = video.get("framerate_value")
        try:
            fv = float(framerate_value) if framerate_value is not None else 0.0
        except (TypeError, ValueError):
            fv = 0.0
        if framerate_mode == "peak" and fv > 0:
            args.extend(["--rate", str(fv), "--pfr"])
        elif framerate_mode == "constant" and fv > 0:
            args.extend(["--rate", str(fv), "--cfr"])
        extra_options = str(video.get("extra_options") or "").strip()
        if extra_options:
            args.extend(["--encopts", extra_options])

    audio = preset.get("audio") or {}
    if isinstance(audio, dict):
        mode = str(audio.get("mode") or "encode").strip()
        if mode == "passthrough":
            args.extend([
                "--audio-lang-list", "all",
                "--all-audio",
                "--audio-copy-mask", "eac3,ac3,aac,truehd,dts,dtshd,mp2,mp3,opus,vorbis,flac,alac",
                "--aencoder", "copy",
                "--audio-fallback", str(audio.get("encoder") or "opus"),
            ])
        elif mode == "copy_with_fallback":
            args.extend([
                "--audio-lang-list", "all",
                "--all-audio",
                "--aencoder", "copy",
                "--audio-fallback", str(audio.get("encoder") or "opus"),
            ])
        else:  # encode
            encoder = str(audio.get("encoder") or "opus").strip()
            args.extend(["--audio-lang-list", "all", "--all-audio", "--aencoder", encoder])
            bitrate = int(audio.get("bitrate") or 0)
            if bitrate > 0:
                args.extend(["--ab", str(bitrate)])
            mixdown = _MIXDOWN_MAP.get(str(audio.get("mixdown") or "").strip())
            if mixdown:
                args.extend(["--mixdown", mixdown])

    container = preset.get("container") or {}
    if isinstance(container, dict):
        fmt = str(container.get("format") or "").strip()
        if fmt:
            args.extend(["-f", fmt])
        if container.get("chapter_markers"):
            args.append("--markers")

    subtitles = preset.get("subtitles") or {}
    if isinstance(subtitles, dict):
        mode = str(subtitles.get("mode") or "all").strip()
        if mode == "all":
            args.append("--all-subtitles")
        elif mode == "first":
            args.extend(["--subtitle", "1"])
        # "none" -> no subtitle arg added

    filters = preset.get("filters") or {}
    if isinstance(filters, dict):
        deint = str(filters.get("deinterlace") or "off").strip()
        if deint != "off" and deint in _DEINTERLACE_MAP:
            args.extend(_DEINTERLACE_MAP[deint])
        denoise = str(filters.get("denoise") or "off").strip()
        if denoise != "off" and denoise in _DENOISE_MAP:
            args.extend(_DENOISE_MAP[denoise])

    return args
