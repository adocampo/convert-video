# Changelog

All notable changes to this project will be documented in this file.

## [1.5.2] - 2026-04-10

### Added in 1.5.2

- **`--install-service` flag**: new CLI option that installs the systemd user unit file for running clutch as a background service on Linux, with automatic binary path detection and daemon reload.

## [1.5.1] - 2026-04-10

### Added in 1.5.1

- **Watcher editing**: existing watchers can now be edited in-place from the dashboard instead of having to remove and re-add them.
- **Queue filters**: the queue panel now has a filename search box and a status dropdown to filter visible jobs.
- **Collapse / Expand all**: a toggle button in the queue header collapses or expands every job card at once.
- **Job counter**: the queue header shows a filtered/total job count.
- **Clear queue modes**: the "Clear queue" button is now a dropdown with three options — clear finished, clear queued, or clear all.
- **Custom dropdown selects**: all native `<select>` elements in the dashboard are replaced with styled dropdown components matching the rest of the UI.

### Changed in 1.5.1

- Toast notifications now appear centered at the top of the screen instead of the bottom-right corner.
- Form status messages (queue job, pause, resume, cancel, clear, etc.) are now shown as toasts instead of inline text.
- Active/queued jobs in the queue list now sort in submission order (ascending); finished jobs sort newest-first.

### Fixed in 1.5.1

- Fixed `AttributeError: 'NoneType' object has no attribute 'get'` in `check_already_converted()` when MediaInfo outputs `{"media": null}`.
- Fixed active jobs disappearing from the dashboard when more than 50 jobs were queued (query now uses a UNION to fetch all active jobs without limit).
- Removed empty vertical space left by unused status-line elements.

## [1.5.0] - 2026-04-09

### Added in 1.5.0

- **Conversion scheduling system**: new Schedule tab in the settings modal lets you define manual time-window rules and electricity-price-based rules that automatically pause and resume conversions.
- **REE PVPC provider**: real Spanish consumer electricity prices (PVPC) from Red Eléctrica, free and without API key, available as a price provider alongside Energy-Charts and ENTSO-E.
- **Price chart**: the Schedule tab shows today's hourly electricity prices with cheapest-hours highlighting, a threshold line, and a summary with current price, min, max, and cheapest hour ranges.
- **Toast notifications**: floating auto-dismiss notifications replace the old static status line in the hero section.
- Schedule enforcement: saving settings that transition to "blocked" immediately pauses running jobs; manual resume is refused while the schedule blocks conversions.

### Changed in 1.5.0

- All electricity prices in the dashboard are now displayed in EUR/kWh instead of EUR/MWh.
- The max-price threshold input uses cent-level precision (step 0.0001 EUR/kWh).
- The update-check staleness window changed from once-per-calendar-day to a 12-hour TTL.
- The `--version` flag now runs the daily update check before printing the version.

### Fixed in 1.5.0

- Schedule status bar in the settings modal now shows the correct red/green colours (CSS class prefix mismatch).
- Schedule chip in the hero bar now correctly shows red when blocked (was using a non-existent CSS variable).
- The disabled-schedule status bar is now hidden instead of leaving an empty grey strip.
- Watchers checkboxes layout changed to an inline row.
- The settings modal content area is now scrollable (was collapsing to zero height).
- Bidding-zone selector now shows country names instead of raw codes.

## [1.4.1] - 2026-04-09

### Changed in 1.4.1

- Removed ~870 lines of dead inline HTML/CSS/JS from the service module that were superseded by the external dashboard assets.

## [1.4.0] - 2026-04-08

### Added in 1.4.0

- Service jobs can now be paused and resumed from the dashboard or HTTP API without stopping the service.
- The service now persists live HandBrake runtime metadata so detached conversions can continue after the service process restarts when the encoder process is still alive.

### Changed in 1.4.0

- Stopping the service now pauses and detaches active conversions so the next service start can reattach to them instead of restarting them immediately from zero.
- Queue management now treats paused jobs as active jobs for watcher duplicate suppression, queue clearing, cancellation, and dashboard status rendering.
- Legacy runtime state now migrates into the branded `clutch` state directory, and the bundled systemd unit now only grants write access to `~/.local/state/clutch`.

### Fixed in 1.4.0

- Conversion ETA reporting now excludes time spent paused.
- Detached conversions whose encoder process is gone now fall back cleanly to the queue with a restart-from-beginning message on the next service start.

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
