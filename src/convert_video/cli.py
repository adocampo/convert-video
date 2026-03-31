#!/usr/bin/env python3
import argparse
import glob
import os
import subprocess
import sys
from typing import List

from convert_video import get_version
from convert_video.output import info, warning, error
from convert_video.mediainfo import VIDEO_EXTENSIONS, show_source_info, check_already_converted
from convert_video.converter import (
    install_signal_handlers, convert_video, confirm_prompt, poweroff_with_countdown,
)
from convert_video.updater import check_for_updates, upgrade
from convert_video.iso import is_iso_file, scan_iso, select_main_title, display_titles

install_signal_handlers()


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


def find_video_files(pattern: str) -> List[str]:
    """Find video files recursively in directories matching a glob pattern."""
    cwd = os.getcwd()
    matched_dirs = []

    if pattern == "*":
        matched_dirs = [cwd]
    else:
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


def main():
    parser = argparse.ArgumentParser(
        description="Convert video files using HandBrakeCLI and preserve all audio and subtitle tracks."
    )

    # ── Input / Output ───────────────────────
    io_group = parser.add_argument_group("input/output")
    io_group.add_argument("input_files", nargs="*", default=[], help="Video files or directories to convert.")
    io_group.add_argument("-o", "--output", default="", help="Output directory for converted files.")
    io_group.add_argument("--find", nargs="?", const="*", default=None, metavar="PATTERN",
                          help="Recursively search for video files in directories matching the pattern, "
                               "or current directory if no pattern is given.")
    io_group.add_argument("-r", "--recursive", action="store_true",
                          help="Recursively search directories for video files matching the given patterns.")
    io_group.add_argument("-ds", "--delete-source", action="store_true",
                          help="Delete the original source file after a successful conversion.")

    # ── Encoding ─────────────────────────────
    enc_group = parser.add_argument_group("encoding")
    enc_group.add_argument("-c", "--codec", default="nvenc_h265",
                           help="Video codec: nvenc_h265 (default), nvenc_h264, av1, x265.")
    enc_group.add_argument("-s", "--slow", action="store_true", help="Use slow encoding speed.")
    enc_group.add_argument("-f", "--fast", action="store_true", help="Use fast encoding speed.")
    enc_group.add_argument("-n", "--normal", action="store_true", help="Use normal encoding speed (default).")
    enc_group.add_argument("-ap", "--audio-passthrough", action="store_true",
                           help="Pass through original audio tracks.")
    enc_group.add_argument("--force", action="store_true",
                           help="Force conversion even if file is already in the target codec.")

    # ── Behaviour ────────────────────────────
    beh_group = parser.add_argument_group("behaviour")
    beh_group.add_argument("-y", "--yes", action="store_true",
                           help="Automatically accept transcoding without prompts.")
    beh_group.add_argument("--verbose", action="store_true",
                           help="Show verbose output from HandBrakeCLI.")
    beh_group.add_argument("-po", "--poweroff", action="store_true",
                           help="Power off the system after conversion.")

    # ── Info ─────────────────────────────────
    info_group = parser.add_argument_group("info")
    info_group.add_argument("-si", "--source-info", action="store_true",
                            help="Show source information about a single video file.")
    info_group.add_argument("-v", "--version", action="version",
                            version=f"convert-video {get_version()}")
    info_group.add_argument("--update", action="store_true",
                            help="Check if a newer version is available on GitHub.")
    info_group.add_argument("--upgrade", action="store_true",
                            help="Upgrade to the latest version from GitHub.")

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
        if is_iso_file(input_file):
            # ISO disc image: scan for titles and pick the main feature
            titles = scan_iso(input_file)
            if not titles:
                warning(f"No titles found in ISO: {input_file}")
                continue
            main_title = select_main_title(titles)
            display_titles(titles, main_title['index'])
            info(f"Selected title {main_title['index']} ({main_title['duration_str']})")

            success = convert_video(
                input_file, args.output, args.codec, speed,
                args.audio_passthrough, args.verbose,
                title=main_title['index'],
                resolution_override=main_title.get('resolution') or None,
                audio_tracks=main_title.get('audio_tracks', []),
            )
            if success:
                if args.delete_source:
                    try:
                        os.remove(input_file)
                        info(f"Deleted source: {input_file}")
                    except OSError as e:
                        warning(f"Could not delete source file '{input_file}': {e}")
            else:
                warning(f"Conversion failed for: {input_file}")
            continue

        if not args.force:
            status = check_already_converted(input_file, args.codec, args.force)
            if status == 'skip':
                skipped += 1
                continue
            # 'warn' and 'convert' both proceed to conversion

        if convert_video(input_file, args.output, args.codec, speed, args.audio_passthrough, args.verbose):
            if args.delete_source:
                try:
                    os.remove(input_file)
                    info(f"Deleted source: {input_file}")
                except OSError as e:
                    warning(f"Could not delete source file '{input_file}': {e}")
        else:
            warning(f"Conversion failed for: {input_file}")

    if skipped:
        info(f"\n{skipped} file(s) skipped (already converted).")


    print("Process complete.")

    # Power off if requested
    if args.poweroff:
        poweroff_with_countdown()


if __name__ == "__main__":
    main()
