# Changelog

All notable changes to this project will be documented in this file.

## [1.7.14] - 2026-04-17

### Fixed in 1.7.14

- **Changelog preview stays visible during upgrade**: the changelog preview in System > About now remains visible while the update is in progress and smoothly hides once the install completes (step 6), instead of disappearing the moment the upgrade starts.
- **CSS fix for hidden field rows**: `.field-row[hidden]` now correctly applies `display: none`, fixing the issue where the `display: grid` rule on `.field-row` overrode the HTML `hidden` attribute.

## [1.7.13] - 2026-04-17

### Improved in 1.7.13

- **Countdown before service restart**: after the new version is installed, the progress label shows a 3-second countdown ("Restarting in 3…", "2…", "1…") before restarting the service, giving the browser time to reflect the final state.
- **Changelog preview hidden during update**: the changelog preview in System > About is now hidden as soon as the update starts, instead of lingering throughout the install process.

## [1.7.12] - 2026-04-17

### Fixed in 1.7.12

- **Scroll-to-top button on Changelog page**: moved the button outside the page section so it is no longer hidden by the section’s `hidden` attribute, and added a fallback `window` scroll listener so the arrow reliably appears when scrolling down.
- **Full page reload after update**: the dashboard now performs a full browser reload once the service restarts on the new version, ensuring all cached assets, changelog, and version info are refreshed cleanly.

## [1.7.11] - 2026-04-17

### Fixed in 1.7.11

- **Changelog preview persists after update**: the changelog summary in System > About now correctly disappears once the updated version is running, instead of lingering after the service restart.
- **Changelog page header noise**: the raw `# Changelog` heading and boilerplate description line are now stripped from the System > Changelog page.
- **Scroll-to-top button not showing**: the floating arrow on the Changelog page was invisible due to an HTML `hidden` attribute that overrode the CSS visibility toggle.

## [1.7.10] - 2026-04-17

### Fixed in 1.7.10

- **Changelog page empty in production**: `CHANGELOG.md` is now bundled inside the installed package as package data so the System > Changelog page works correctly in pipx-installed (non-development) environments. Previously the file was only reachable via relative paths from the source tree.

## [1.7.9] - 2026-04-17

### Improved in 1.7.9

- **Granular update progress**: the upgrade progress bar now tracks real pipx output phases (resolving package, installing, installed version, restarting) instead of jumping from zero to halfway and disappearing. Each phase updates the label and advances the bar incrementally.
- **Changelog cleanup after update**: the update changelog preview in System > About is now force-cleared when the service restarts on the new version, and the full Changelog page cache is invalidated so it picks up the new content immediately.

## [1.7.8] - 2026-04-17

### Added in 1.7.8

- **Scroll-to-top button on Changelog page**: a floating arrow button appears in the bottom-right corner when scrolling down in System > Changelog, allowing one-click navigation back to the top. The button fades away automatically when already at the top.

## [1.7.7] - 2026-04-17

### Added in 1.7.7

- **Filter clear button**: added a "Clear" button inside the filename filter input to reset both the text and status filters in one click (shows × on narrow screens).
- **Delete key clears selected jobs**: pressing Delete with multiple jobs selected now triggers the bulk clear action instead of only clearing the active row.

### Fixed in 1.7.7

- **Input / select height mismatch**: the filter text input and the status dropdown now share the same fixed height so they align perfectly.
- **Responsive header layout**: the Expand all / Clear queue / Auto refresh buttons now stack into a full-width row below the ACTIVITY title at tablet widths instead of wrapping awkwardly, with minimal spacing between the title and the action buttons.

## [1.7.6] - 2026-04-17

### Fixed in 1.7.6

- **Paused job recovery after service restart**: jobs paused during a service stop were failing immediately on restart because the code tried to attach to the dead HandBrake process instead of resuming from the partial encode. The service now detects dead processes and falls through to the resume-partial path correctly.
- **Manual resume of orphaned paused jobs**: resuming a job whose HandBrake process had died threw an error instead of re-queuing. The job is now re-queued automatically (with partial resume if the temp file still exists, or from scratch otherwise).
- **Progress label cleanup**: removed redundant status text ("Paused", "ETA") from the PROGRESS column since those are already shown in dedicated STATUS and ETA columns.

## [1.7.5] - 2026-04-17

### Added in 1.7.5

- **Step-based update progress**: the progress bar now shows real upgrade steps (downloading, verifying, restarting) instead of an indeterminate animation, with the current step label displayed on the button.
- **Sidebar version dot on update check**: the update-available dot now appears immediately after checking for updates, without requiring a page reload.
- **Persistent expanded/collapsed state**: expanded and collapsed job rows are saved to `localStorage` and restored on page reload.

### Changed in 1.7.5

- All jobs are now collapsed by default in the Activity table (previously running, paused and cancelling jobs auto-expanded).
- Update progress bar animation changed from a pulsing width to a smooth sliding indicator.

## [1.7.4] - 2026-04-16

### Added in 1.7.4

- **Keyboard navigation for the jobs table**: Arrow Up/Down to move between rows, Arrow Right to expand, Arrow Left to collapse, Enter to toggle, Space to select/deselect, Delete to clear a job (with confirmation).
- **System > Changelog page**: full changelog history served from the backend via `GET /system/changelog`.
- **Update progress bar**: indeterminate pulsing progress bar next to the update button while a release is being applied.
- **Dirty-tracking for all forms**: Save, Add Watcher, Queue Job, Save Schedule and similar buttons are disabled until the form has unsaved changes.

### Fixed in 1.7.4

- **Watcher crash on first file**: missing `ConversionJob` and `success` imports in `watcher.py` caused a `NameError` that killed the watcher thread after enqueuing the first file, preventing the remaining files from being processed.
- **Bulk actions bar layout shift**: the bar now reserves its height at all times (`visibility` instead of `display: none`) so the table never jumps when a checkbox is toggled.
- **Confirm dialog Enter key**: Enter now activates whichever button is focused (Cancel, Remove, etc.) instead of always confirming.

### Changed in 1.7.4

- Queued jobs are now collapsed by default in the Activity table; only running, paused, and cancelling jobs auto-expand.

## [1.7.3] - 2026-04-16

### Added in 1.7.3

- **Filter pattern for directory jobs**: new Filter field with live preview when submitting a directory. Supports glob wildcards (`*`, `?`, `[2-5]`), character ranges (`[X..Y]` auto-converted to `[X-Y]`), and plain substring matching.
- **`debug()` logging function**: prints to stdout and writes to the file logger for end-to-end visibility.
- **Detailed DEBUG logging** across the filter pipeline (`service.py`) and the `/browse/match` endpoint (`http_handler.py`) — pattern, glob, regex, timing, and result counts.
- **Loading spinner** in the filter preview while the server scans the directory.
- **Include subdirectories toggle** replaced the old checkbox with a full-size toggle knob in both the form and the browser modal footer.
- **Settings > General**: authentication toggle and Save button (previously read-only).
- **User preferences**: per-user date format and theme stored server-side; date format selector on the User Settings page.
- **Personal API tokens** section in User Settings; admin "All API Tokens" view in System > Users.
- **Sidebar version link**: click the version number to scroll to the About section; update-available dot indicator.
- **Log download auth**: log file downloads now pass the bearer token via query string so `<a href>` links work with authentication enabled.

### Fixed in 1.7.3

- **Recursive directory scan performance**: replaced sequential `os.walk` (36 s on NAS) with a two-tier strategy — fast path filters top-level directories first (same as CLI `--find`, ~0.2 s), falling back to a parallel `ThreadPoolExecutor` scan with 8 workers (~3 s).
- **Log viewer level filter**: changed from exact match to threshold-based (selecting DEBUG now shows all levels, not only DEBUG entries).
- **Log viewer dropdown**: now also sets the server log level via `POST /config` so DEBUG entries are actually written.
- **Unclosed bracket auto-close**: `[2..3` patterns no longer break fnmatch — a missing `]` is appended automatically.
- **`BrokenPipeError` noise**: silenced `BrokenPipeError` and `ConnectionResetError` in `handle_error` instead of logging them as ERROR.
- **Auth-disabled flow**: `/login` redirects to `/` when auth is off; anonymous users get admin-level UI.
- **Sidebar active badge**: counts queued + running + paused jobs (was missing queued).
- **Date formatting**: all timestamps (jobs, tasks, logs, log files) now respect the configured date format.

### Changed in 1.7.3

- `_collect_directory_input_files` accepts an optional `filter_pattern` parameter and builds an `fnmatch` or substring filter internally.
- `save_service_config` / `load_service_config` now persist `default_date_format`.
- `store.py`: added `default_date_format` column migration; fixed `gpu_devices` double-parse.
- `auth.py`: added `admin_delete_token` and `list_all_tokens` methods.
- `login.html`: early redirect when auth is disabled.

## [1.7.2] - 2026-04-15

### Changed in 1.7.2

- **Modularized `service.py`**: split the monolithic 4 300-line module into six focused files — `store.py` (job data & SQLite persistence), `notifications.py` (Telegram / webhook delivery), `watcher.py` (directory watcher & worker handles), `logs.py` (log file helpers & system stats), `http_handler.py` (HTTP request handler & static assets), and a slimmed-down `service.py` (orchestration only). Public API is unchanged; all existing imports continue to work via re-exports.

## [1.7.1] - 2026-04-15

### Fixed in 1.7.1

- **Telegram notifications**: fixed HTTP 400 error caused by URL-encoding the bot token (`:` was encoded as `%3A`) and by Markdown v1 parse mode choking on special characters in filenames. Switched to HTML parse mode for reliable message delivery.
- **Webhook notifications**: fixed HTTP 400 with Slack-compatible webhooks by adding a `text` field to the JSON payload alongside the structured `event`/`job` data.

### Changed in 1.7.1

- Notification channel list now renders as a table (matching the Users page style) with Type, Name, Events, Status columns and inline Test / Edit / Delete buttons per row.
- All notification form fields (Name, Bot Token, Chat ID, URL, Headers, Events, Enabled) are now aligned on the same grid with uniform widths.

## [1.7.0] - 2026-04-14

### Added in 1.7.0

- **Notification system** (Settings > Notifications): configure Telegram bots and generic webhook endpoints to receive notifications on job events.
- **Telegram integration**: send messages via Telegram Bot API with Markdown-formatted job summaries (file name, codec, status, message).
- **Webhook integration**: send JSON POST payloads to any HTTP/HTTPS endpoint with optional custom headers.
- **Per-channel event selection**: choose which events trigger each channel (job succeeded, job failed, job cancelled).
- **Test notifications**: verify channel configuration with a one-click test button that sends a sample message.
- **Notification API**: `GET /config/notifications`, `POST /config/notifications`, `POST /config/notifications/test`, `DELETE /config/notifications/:id`. Admin role required.

### Changed in 1.7.0

- Notifications fire asynchronously in background threads to avoid blocking worker processing.

## [1.6.3] - 2026-04-14

### Added in 1.6.3

- **Task history** (System > Tasks): admin-only page with sortable task table showing status badges, file name, codec, size (with compression %), duration, and submitted date. Supports filtering by status/codec, text search, and pagination.
- **Log file management** (System > Logs > Log Files): Sonarr-style log files tab with download and delete actions per file, plus a "Clear old logs" bulk action for rotated files.
- **Log file management API**: `GET /system/logs/download` (download individual log file), `DELETE /system/logs/files` (delete single file or clear all rotated files). Admin role required.
- **User avatars**: users list now displays Gravatar-based avatars with initials fallback.

### Fixed in 1.6.3

- Log Viewer tab was visible even when hidden due to CSS `display: flex` overriding the HTML `hidden` attribute. Log Files is now correctly shown as the default tab.

### Changed in 1.6.3

- Tasks table fully styled with sticky headers, hover effects, status badge pills (colour-coded per status), and text ellipsis for long file names.
- Log tabs use explicit `style.display` toggling for reliable show/hide behaviour.

## [1.6.2] - 2026-04-14

### Added in 1.6.2

- **Application file logging**: all application events are now written to daily-rotating log files at `~/.local/state/clutch/logs/` using Python `TimedRotatingFileHandler`.
- **Log viewer** (System > Logs): real-time log viewer with level filter, text search, log file selector, auto-refresh (5s polling), and pagination.
- **Log reading API**: `GET /system/logs` (paginated, filterable by level/text/file) and `GET /system/logs/files` (list available log files). Admin role required.
- **Runtime log level changes**: changing the log level in Settings > Logs takes effect immediately without restarting the service.
- **Automatic log cleanup**: rotated log files beyond the configured retention period are automatically deleted.

### Changed in 1.6.2

- `output.py` refactored: console output functions (`info`, `warning`, `error`, `success`, `skip`, `deleted`) now also write to the file logger, providing dual output (coloured terminal + structured log file).

## [1.6.1] - 2026-04-14

### Added in 1.6.1

- **Sonarr-style sidebar**: sidebar now uses collapsible Settings and System groups with accordion behaviour (only one group expanded at a time).
- **Flyout menus**: in tablet mode (collapsed sidebar), clicking a group icon opens a flyout panel instead of expanding inline sub-pages.
- **Nav link tooltips**: collapsed sidebar shows label tooltips on hover via CSS pseudo-elements.
- **Settings > User page**: new page with profile info, theme preference, and inline change-password form accessible to all roles.
- **Unified user popup**: clicking avatar/username in the sidebar footer opens a popup menu with Settings and Sign out, consistent across desktop, tablet, and mobile.
- **User preferences backend**: new `user_preferences` table and API routes for per-user theme and settings.

### Changed in 1.6.1

- Sidebar restructured from 6 flat pages to 4 top-level links + 2 collapsible groups (Settings with 6 sub-pages, System with 4 sub-pages).
- Role-based sidebar visibility: operators see Activity, Jobs, Watchers, Schedule, and Settings > User only; admin-only pages are hidden.
- Sidebar footer replaced inline icon buttons with a click-to-popup menu to avoid username truncation in narrow sidebars.

## [1.6.0] - 2026-04-14

### Added in 1.6.0

- **User authentication system**: optional multi-user auth with role-based access control (admin, operator, viewer). Bearer token authentication for both the dashboard and the API.
- **First-run setup wizard**: on first launch, a setup page lets you create the initial admin account or skip to run without authentication.
- **Login page**: dedicated sign-in page with username/password, "Forgot password" flow, and password reset via email link.
- **User management dashboard**: new Users page in the sidebar with full CRUD for user accounts (admin only), change-password form, and role assignment.
- **API tokens**: users can create and revoke named API tokens with configurable expiry (1–3650 days) for headless/script access.
- **SMTP settings**: admins can configure SMTP (host, port, username, password, TLS/SSL, from address) from the dashboard for password-reset emails.
- **SMTP test button**: "Test connection" button sends a test email to the current user to verify SMTP settings before relying on them.
- **Password reset via email**: full forgot-password flow — request reset link, receive email, set new password — with 1-hour expiry tokens.
- **Rate limiting**: login attempts are rate-limited to 5 per IP within 15 minutes to mitigate brute-force attacks.

### Changed in 1.6.0

- All existing API routes now enforce role-based authorization when auth is enabled (admin for config/updates, operator for jobs/watchers, viewer for read-only).
- SMTP sending now auto-detects port 465 (implicit SSL via `SMTP_SSL`) vs other ports (STARTTLS), so users don't need to worry about the TLS checkbox when using port 465.
- Dashboard initialization now properly waits for auth state before loading page-specific data, preventing empty users/SMTP sections on first render.

### Security in 1.6.0

- Passwords hashed with scrypt (n=16384, r=8, p=1, 32-byte salt, 64-byte derived key).
- Tokens stored as SHA-256 hashes; timing-safe comparison via `hmac.compare_digest`.
- Session tokens hidden from the API tokens list to avoid confusion.
- Password reset endpoints never reveal whether an email exists (anti-enumeration).

## [1.5.5] - 2026-04-13

### Added in 1.5.5

- **Jobs table view**: the Activity page now displays jobs in a sortable table instead of cards. Click any column header (Name, Status, Progress, Codec, Size, ETA, Submitted) to sort ascending/descending.
- **Two-column job details**: expanded job details show source and output info side-by-side, with media metadata in each column.
- **Conversion duration**: job details now show how long the conversion took, computed from start/finish timestamps.
- **System Monitor**: new section in Settings showing CPU (cores, load average, temperature), RAM usage, GPU stats (VRAM, utilization, temperature, fan speed), and disk mount points with usage bars. Auto-refreshes every 5 seconds while visible.
- **Custom confirm dialog**: destructive actions (remove watcher, clear job) now use a themed modal instead of the browser's native confirm.
- **Watcher edit highlight**: editing a watcher scrolls to it and plays a brief highlight pulse animation.
- **Watcher button states**: Edit/Remove buttons are disabled while a watcher is being edited.

### Changed in 1.5.5

- **Theme selector**: replaced the toggle button with a Light/Dark dropdown select.
- **About section**: restructured into separate Version, Updates, and Changelog rows.
- **File browser**: redesigned from card layout to a compact table with folder/file icons, Cancel/Ok footer.
- **Default Settings labels**: checkbox descriptions now explain what each option does.
- **Changelog formatting**: update changelog rendered as HTML with bold headings, bullet lists, and inline code.
- **Responsive layout**: form fields now stack at 920px instead of 640px to avoid cramped intermediate widths. Activity header buttons share a row in mobile instead of going full-width. Dropdown menus open left-aligned on small screens.

### Fixed in 1.5.5

- Fixed update button stretching to full width inside grid layout.

## [1.5.4] - 2026-04-13

### Added in 1.5.4

- **Queue reordering**: queued jobs now have a priority field; a "Convert next" button in the dashboard promotes any queued job to the front of the queue.
- **Pause releases worker**: pausing a running conversion now detaches the worker so it can immediately pick up the next queued job, instead of blocking until the paused job is resumed.
- **Conversion resume from partial encodes**: if a conversion is interrupted (power loss, service restart) and a partial temp file exists, the encoder resumes from where it left off using HandBrake `--start-at` and joins the segments with `mkvmerge`.

### Changed in 1.5.4

- **Package renamed** from `convert_video` to `clutch` to match the project name. All internal imports updated.
- Resuming a paused-detached job no longer falsely shows it as "running" until a worker is actually free to pick it up.

### Fixed in 1.5.4

- Fixed accumulated `.progress.log` and `.tmp.mkv` files never being cleaned up after conversion or recovery.
- Fixed `[Errno 2] FileNotFoundError` race condition when deleting temp files on network storage (TOCTOU replaced with try/except).
- Fixed orphaned temp files from previous conversion attempts not being removed on success.
- Fixed resume-join failure permanently marking the job as failed instead of requeuing for a fresh encode.

## [1.5.3] - 2026-04-12

### Added in 1.5.3

- **Per-watcher conversion overrides**: each watcher can now override output directory, codec, encode speed, audio passthrough, and force re-encode independently from the global defaults.
- **Media info in job details**: the dashboard now shows source and output media metadata (video codec, resolution, audio tracks, subtitle tracks) for each job.
- **Subdirectory structure preservation**: when a watcher has an output directory and is recursive, the relative subfolder structure from the watched directory is mirrored in the output.
- **Empty subdirectory cleanup**: watchers with recursive + delete_source now automatically remove empty subdirectories after each scan.
- **qBittorrent integration script** (`qbt-hardlink-to-watch.sh`): standalone post-download script that hardlinks completed torrent video files into clutch watch directories, with automatic series/movie classification by qBittorrent category (`sonarr`/`radarr`) or torrent name patterns.

### Changed in 1.5.3

- Button and custom-select padding reduced for a more compact UI.

### Fixed in 1.5.3

- Fixed `build_output_subdir` producing invalid `../../../` paths when the input file and working directory were on different filesystem trees.

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
