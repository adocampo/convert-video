# Progress

## Goal

Add a service mode so machine A can convert files requested from other machines in the LAN, add an automatic watched-directory mode, and expose a small browser-based UI that can be used remotely from machine B.

## Current Status

- In progress.
- The original local CLI flow is still the reference path and has not been replaced.
- The first working implementation slice for service mode is now in the repository.

## Completed

- Added a new service runtime module at [src/convert_video/service.py](src/convert_video/service.py).
- Added a `ConversionJob` dataclass to represent queued conversion work.
- Added a SQLite-backed `JobStore` with queued, running, succeeded, failed, skipped, and cancelled states.
- Added a worker loop in `ConversionService` to execute queued jobs sequentially.
- Added a minimal HTTP API with:
  - `GET /health`
  - `GET /jobs`
  - `GET /jobs/{id}`
  - `POST /jobs`
  - `DELETE /jobs/{id}`
- Added a polling-based directory watcher that can enqueue newly detected video files after they become stable.
- Added allowed-root validation so the service can restrict filesystem access.
- Added a client helper to submit jobs to the remote service over HTTP.
- Wired the main CLI so it can either convert locally, start the service, or submit jobs to a remote service.
- Refactored the converter so service jobs can run without the interactive progress bar and can return the effective output path.
- Documented the new service and watchdog usage in `README.md`.
- Validated the touched files with workspace diagnostics.
- Validated the CLI help output with the project virtual environment.
- Added a built-in browser dashboard served by machine A so jobs can be submitted and inspected visually from another machine.
- Added a service summary endpoint for the UI to expose allowed roots and watched directories.
- Added runtime service administration from the web UI so allowed roots, default conversion settings, and watched directories can be updated without restarting the service.
- Added watcher management endpoints to create and remove watched directories while the service is running.
- Made the web dashboard resilient to plain HTML form submissions so it no longer fails with `GET /?...` when the browser falls back to non-JavaScript form handling.
- Added live progress tracking for running jobs so the UI can show percentage completion instead of only queue state.
- Fixed runtime `allowed_roots` updates so the admin UI validates by filesystem existence instead of the previous root filter.
- Added throttled progress logging to the service stdout while jobs are encoding.

## In Progress

- End-to-end runtime validation with real conversions through the HTTP service.
- CLI polish for service-oriented workflows beyond job submission, such as richer remote status inspection.
- Operational hardening for long-running daemon use.
- UI polish and optional extra controls for service administration.
- End-to-end validation of the new runtime admin controls against a live running service.

## Next Steps

1. Refactor [src/convert_video/converter.py](src/convert_video/converter.py) so service execution can disable TTY progress cleanly and report output paths deterministically.
2. Update [src/convert_video/cli.py](src/convert_video/cli.py) with service/server/client/watcher flags and routing.
3. Add integration validation against a real running service and real media paths visible from machine A.
4. Decide whether to add extra client commands for remote status and cancellation.
5. Add operational artifacts such as a sample systemd unit and a service configuration example.
6. Decide whether watcher edits should also support modifying existing watcher intervals instead of only add/remove.

## Notes

- First implementation target: machine A operates on paths it can already access, including pre-mounted network shares.
- The first version does not upload files from B to A or mount remote shares automatically.
- The service is intentionally single-worker for now to avoid unsafe parallel GPU or CPU scheduling until behavior is defined more clearly.
- The CLI parse path is validated, but actual remote conversion has not yet been exercised against a live server in this session.
- The web UI is served by the same HTTP process as the API, so it remains dependency-free and can be opened from any machine that can reach machine A over the LAN.
- Runtime changes made in the web UI affect future jobs and future watcher activity, but they are not yet persisted across full service restarts.
- The service now parses request paths independently from query strings, which avoids false 404s on dashboard form submissions.
- Job progress is stored in the service database and exposed through the existing jobs API, so the browser can refresh it without extra endpoints.
- Runtime admin changes to `allowed_roots` now work correctly even when the new roots expand beyond the previous restriction set.
