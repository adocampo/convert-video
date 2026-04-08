# Changelog

All notable changes to this project will be documented in this file.

## [1.3.1] - 2026-04-08

### Fixed in 1.3.1

- HandBrake-produced HEVC files are now detected more reliably from MediaInfo metadata, including variants that expose `Writing_Application` and different encoder fields.
- Local runs and service jobs now skip a source when its expected converted output already exists, is newer than the source, and is already recognized as converted, preventing duplicate files such as `_converted (1).mkv`.
- Installer, updater, and current documentation references now point at the renamed GitHub repository `adocampo/clutch`.

### Added in 1.3.1

- Regression tests now cover HandBrake detection and duplicate-output skipping logic.

## [1.3.0] - 2026-04-08

### Added in 1.3.0

- **Clutch branding assets**: the project now ships the branded logo and favicon used by the documentation and web dashboard.

### Changed in 1.3.0

- The project is now branded as `clutch` across the CLI, installer, systemd service, dashboard, packaged assets, and documentation.
- The installed console script is now `clutch`; the previous `convert-video` command is no longer installed.
- Upgrade and service migration paths now carry forward legacy `convert-video` state, theme preferences, and service files under the new `clutch` names automatically.

### Repository status

- The GitHub repository now lives at `adocampo/clutch`, and install and self-update commands use the renamed repo.

## [1.2.3] - 2026-04-08

### Added in 1.2.3

- **Daily release checks**: the CLI and service now share a cached daily GitHub release check so users are warned about new versions without repeated requests on every run.
- **Dashboard update control**: the web UI now includes a release icon that can check for updates, show a badge when a newer version is available, and display the changelog delta in the tooltip.

### Changed in 1.2.3

- Normal CLI runs now show the upgrade reminder at most once per day, while `--update` and `--upgrade` continue to work on demand.
- The service now performs its own daily release check, exposes update status to the dashboard, and can install the latest version and restart itself after user confirmation.

## [1.2.2] - 2026-04-08

### Added in 1.2.2

- **One-line installer**: `curl -fsSL https://raw.githubusercontent.com/adocampo/clutch/master/install.sh | bash` now installs the tool without a manual clone.
- **Systemd user unit**: Linux installs now include a dedicated user unit for running the LAN service via `systemctl --user`.

### Changed in 1.2.2

- The installer now supports both local-repo installs and piped installs from the GitHub-hosted `install.sh`.
- The dashboard now shows visible NVIDIA GPUs with model name and total memory instead of raw numeric indices.
- The README now highlights the main features, quick installation options, service usage, and dashboard screenshot more clearly.

## [1.2.1] - 2026-04-07

### Changed in 1.2.1

- `--update` now shows the full changelog between the installed version and the latest available version, including all intermediate versions when there is more than one.

## [1.2.0] - 2026-04-07

### Added in 1.2.0

- **Service mode** (`--serve`): run an HTTP conversion service that accepts jobs from other machines in the LAN.
- **Web dashboard**: built-in browser UI served at the service port with dark/light theme, filesystem browser, queue management, job progress, and live auto-refresh.
- **Parallel workers** (`--workers N`): run multiple local conversions at the same time with a combined terminal progress display.
- **Multi-GPU round-robin** (`--gpus 0,1`): distribute NVENC jobs across multiple NVIDIA GPUs.
- **Remote job submission** (`--server-url`): submit conversion jobs to a remote service from the CLI.
- **Watched directories** (`--watch-dir`): automatically enqueue new video files that appear in monitored directories.
- **Runtime administration**: change worker count, GPU indices, allowed roots, default job settings, and watched directories from the web dashboard without restarting the service.
- **Persistent service configuration**: worker count, GPU devices, allowed roots, defaults, and watchers are stored in the service database and survive restarts.
- **Directory-based job submission**: queue all video files in a directory at once from the dashboard.
- **Job retry and bulk clear**: retry failed/cancelled jobs and clear finished jobs from the queue.

### Changed in 1.2.0

- Multi-file progress display now shows full filenames on their own line with a dynamic-width progress bar underneath, matching the single-file display style.
- Completed jobs in multi-file mode emit `[ OK ]`, `[FAIL]`, `[SKIP]` lines identical to single-file output.
- Web dashboard assets (HTML, CSS, JS) are packaged inside the Python package and served via `importlib.resources`.

### Notes

- Multi-GPU support is implemented but has not been tested with actual multi-GPU hardware due to lack of compatible hardware.

## [1.1.2] - 2026-04-01

### Fixed in 1.1.2

- Fixed the terminal progress bar so it redraws correctly when the terminal is resized and disappears cleanly when conversion finishes.
- Fixed the end-of-run crash caused by a local `success` variable shadowing the output helper.
- Removed the broken `dev.sh` development workflow in favor of a simpler manual virtual environment setup.

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
