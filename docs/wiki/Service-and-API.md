# Service and API

## Start service

```bash
clutch --serve --listen-host 0.0.0.0 --listen-port 8765 --allow-root /srv/media
```

## Dashboard

Open:

- `http://localhost:8765/` on the host machine
- `http://<host-ip>:8765/` from LAN clients

## Persistent runtime state

Service configuration is persisted in the service database (`--service-db`), including:

- worker count
- GPU device list
- watcher definitions
- default job settings
- allowed roots

## Workers and GPU scheduling

- Queue workers process jobs in parallel.
- NVENC jobs can rotate across configured GPU indices in round-robin mode.

## Watchers

Watchers poll filesystem paths and enqueue files once they are stable for `--watch-settle-time` seconds.

## HTTP endpoints

Current core endpoints:

- `GET /`
- `GET /health`
- `GET /config`
- `GET /watchers`
- `GET /jobs`
- `GET /jobs/<job_id>`
- `POST /config`
- `POST /watchers`
- `POST /jobs`
- `POST /jobs/<job_id>/pause`
- `POST /jobs/<job_id>/resume`
- `POST /jobs/<job_id>/retry`
- `DELETE /watchers/<watcher_id>`
- `DELETE /jobs/<job_id>`

Remote upload endpoints:

- `POST /upload`
- `POST /upload-and-convert`
- `POST /stream-convert`

## Security notes

- Restrict roots with `--allow-root`.
- Prefer private LAN exposure or reverse proxy auth if exposed beyond LAN.
- Use API token when remote upload mode is enabled.
