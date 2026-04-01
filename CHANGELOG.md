# Changelog

All notable changes to this project will be documented in this file.

## [1.1.2] - 2026-04-01

### Fixed in 1.1.2

- Fixed the terminal progress bar so it redraws correctly when the terminal is resized and disappears cleanly when conversion finishes.
- Fixed the end-of-run crash caused by a local `success` variable shadowing the output helper.
- Removed the broken `dev.sh` and `convert-video-dev` workflow in favor of a simpler manual virtual environment setup.

### Changed in 1.1.2

- Improved terminal output formatting with consistent status labels and colors for success, skip, warning, error, and deletion messages.
- Display the file name separately from the progress bar and show the elapsed conversion time in the final status line.

## [1.1.1] - 2026-04-01

### Fixed

- Output files now always use `.mkv` extension regardless of source format, matching the actual Matroska container produced by HandBrakeCLI.

## [1.1.0] - 2026-04-01

### Added in 1.1.0

- **Modular architecture**: refactored monolithic `cli.py` into separate modules (`output`, `mediainfo`, `converter`, `updater`, `iso`).
- **ISO disc image support**: automatically scans ISO images, detects all titles, and converts the main feature (longest duration) with per-track audio channel preservation.
- **`--delete-source` / `-ds`**: delete the original source file after a successful conversion.
- **Categorized `--help`**: arguments organized into input/output, encoding, behaviour, and info groups.
- **`.gitignore`**: standard Python ignores.

## [1.0.0] - 2026-03-31

### Added in 1.0.0

- Initial packaged release with `pyproject.toml` and `pipx` support.
- **`-v` / `--version`**: display current version (reassigned from `--verbose`; `--verbose` remains as long form).
- **`--update`**: check if a newer version is available on GitHub.
- **`--upgrade`**: self-update via `pipx` from GitHub.
- Video conversion with HandBrakeCLI preserving all audio and subtitle tracks.
- Smart codec detection and skip logic (avoid re-encoding already converted files).
- Multiple encoding speeds (`-s` slow, `-n` normal, `-f` fast) and codecs (`nvenc_h265`, `nvenc_h264`, `x265`, `av1`).
- Audio passthrough (`-ap`) or automatic per-track opus encoding with channel-aware mixdown.
- Recursive directory search (`-r`, `--find`).
- Source info display (`-si`).
- Power off after conversion (`-po`).
- Progress bar with tqdm.
- Signal handling (single Ctrl+C skips file, double Ctrl+C aborts).
