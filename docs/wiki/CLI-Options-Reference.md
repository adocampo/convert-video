# CLI Options Reference

This page documents all current CLI options grouped by feature.

## Input and output

- `input_files`:
  - Positional paths (files/directories) to process.
- `-o, --output`:
  - Output directory for converted files.
- `--find [PATTERN]`:
  - Recursive file discovery by pattern.
  - If omitted, uses `*` in current directory.
- `-r, --recursive`:
  - Recursive traversal for directory inputs.
- `-ds, --delete-source`:
  - Delete original source after successful conversion.

## Encoding

- `-c, --codec`:
  - `nvenc_h265` (default), `nvenc_h264`, `av1`, `x265`.
- `-s, --slow`:
  - Slow preset mode.
- `-f, --fast`:
  - Fast mode.
- `-n, --normal`:
  - Normal mode (default behavior).
- `-ap, --audio-passthrough`:
  - Keep original audio tracks.
- `--force`:
  - Convert even when smart detection would skip.
- `--gpus`:
  - Comma-separated NVENC GPU indices, for example `0,1`.

## Behaviour

- `-y, --yes`:
  - Non-interactive confirmation.
- `--verbose`:
  - Show verbose encoder output.
- `-w, --workers`:
  - Number of local workers (minimum 1).
- `-po, --poweroff`:
  - Power off when conversion finishes.
- `--server-url`:
  - Submit jobs by path to remote service API.

## Remote upload mode

- `--remote-server`:
  - Upload local files to a remote Clutch server (`host:port`).
- `--token`:
  - API token (also read from `CLUTCH_TOKEN`).
- `--upload-workers`:
  - Parallel upload workers (default 2).
- `--download`:
  - Download converted files back after completion.
- `--stream`:
  - Upload + convert + download in one streaming request.

Notes:

- `--remote-server` and `--server-url` are mutually exclusive.
- Use `--server-url` when the server can already access source paths.
- Use `--remote-server` when source files only exist on the client machine.

## Service mode

- `--serve`:
  - Run HTTP service and dashboard.
- `--listen-host`:
  - Bind host, default `0.0.0.0`.
- `--listen-port`:
  - Bind port, default `8765`.
- `--service-db`:
  - SQLite queue/config database path.
- `--allow-root`:
  - Allowed filesystem roots. Repeatable.
- `--watch-dir`:
  - Add watched directory. Repeatable.
- `--watch-recursive`:
  - Recursive watcher mode.
- `--watch-poll-interval`:
  - Poll interval in seconds.
- `--watch-settle-time`:
  - Stable time required before enqueue.

## Schedule and electricity price

- `--schedule RULE`:
  - Manual allow/block windows.
- `--schedule-mode {allow,block}`:
  - Interpret manual rules as allow-list or block-list.
- `--price-provider {energy_charts,entsoe}`:
  - Price source.
- `--price-country`:
  - Bidding zone/country code.
- `--price-limit`:
  - Max EUR/MWh threshold.
- `--price-cheapest-hours`:
  - Convert only cheapest N hours.
- `--entsoe-api-key`:
  - ENTSO-E API token.
- `--schedule-priority`:
  - Rule arbitration mode.
- `--schedule-pause-behavior`:
  - `block_new` or `pause_running`.

## Binary path overrides

- `--handbrake-cli PATH`
- `--mediainfo PATH`
- `--mkvpropedit PATH`
- `--mkvmerge PATH`

Use these when dependencies are installed outside PATH.

## Information and maintenance

- `-si, --source-info`:
  - Inspect source metadata.
- `-v, --version`:
  - Show installed version.
- `--update`:
  - Check for newer release.
- `--upgrade`:
  - Upgrade from GitHub.
- `--install-service`:
  - Install Linux systemd user service unit.
