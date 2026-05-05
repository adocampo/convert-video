# Docker

Clutch provides two official Docker images published to the GitHub Container Registry (GHCR). You can also build either variant locally from the included Dockerfiles.

## Quick start

```bash
docker run -d \
  --name clutch \
  -p 8765:8765 \
  -v clutch-config:/config \
  -v /path/to/media:/media \
  ghcr.io/adocampo/clutch:latest
```

Open `http://localhost:8765` in your browser.

---

## Image variants

Clutch is published in two flavors:

| Image | Base | Size | Description |
|-------|------|------|-------------|
| `ghcr.io/adocampo/clutch` | Arch Linux | ~1.5 GB | Full image with shell, package manager. Supports in-place upgrades via `clutch --upgrade`. |
| `ghcr.io/adocampo/clutch-minimal` | scratch | ~280 MB | Stripped image with only the runtime binaries. No shell, no package manager. Must pull/rebuild to upgrade. |

Both images contain the same tools (HandBrakeCLI, mediainfo, mkvmerge, mkvpropedit, Python) and produce identical transcoding results.

### When to use each

- **`clutch`** (recommended): Best for most users. Supports `clutch --upgrade` from the web dashboard, includes a full shell for debugging, and can install additional packages if needed.
- **`clutch-minimal`**: Best when image size matters (CI/CD, bandwidth-constrained environments, NAS with limited storage). Requires `docker pull` or a full rebuild to upgrade.

### Tags

| Tag pattern | Example | Description |
|-------------|---------|-------------|
| `latest` | `clutch:latest` | Latest stable release |
| `<version>` | `clutch:2.2.0` | Specific version |
| `latest` | `clutch-minimal:latest` | Latest stable minimal |
| `<version>` | `clutch-minimal:2.2.0` | Specific minimal version |

---

## Pulling the image

```bash
# Full image (Arch-based)
docker pull ghcr.io/adocampo/clutch:latest

# Minimal image (scratch-based)
docker pull ghcr.io/adocampo/clutch-minimal:latest
```

## Building locally

From the repository root:

```bash
# Full Arch image
docker build -t clutch .

# Minimal scratch image
docker build -f Dockerfile.minimal -t clutch-minimal .
```

The full image (`Dockerfile`) installs all dependencies from the Arch Linux repositories and clutch via pip.

The minimal image (`Dockerfile.minimal`) uses a multi-stage build: it installs everything in Arch, then copies only the required binaries, shared libraries, and Python runtime to a scratch image — resulting in ~82% size reduction.

---

## Pushing to GHCR (maintainers)

1. Authenticate with the GitHub Container Registry:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin
```

1. Build and push both images:

```bash
# Full image
docker build -t ghcr.io/adocampo/clutch:2.2.0 -t ghcr.io/adocampo/clutch:latest .
docker push ghcr.io/adocampo/clutch:2.2.0
docker push ghcr.io/adocampo/clutch:latest

# Minimal image
docker build -f Dockerfile.minimal -t ghcr.io/adocampo/clutch-minimal:2.2.0 -t ghcr.io/adocampo/clutch-minimal:latest .
docker push ghcr.io/adocampo/clutch-minimal:2.2.0
docker push ghcr.io/adocampo/clutch-minimal:latest
```

Alternatively, pushing a Git tag (`v*`) triggers the GitHub Actions workflow at `.github/workflows/docker-publish.yml`, which builds both image variants and pushes them automatically.

---

## Docker Compose

A single `docker-compose.yml` is provided in the repository. It pulls from GHCR by default and includes commented-out options for the minimal image and building from source.

```bash
docker compose up -d
```

### Switching images

Edit `docker-compose.yml` and uncomment the desired `image:` line:

```yaml
services:
  clutch:
    # Pick ONE image:
    image: ghcr.io/adocampo/clutch:latest           # Full (default)
    # image: ghcr.io/adocampo/clutch-minimal:latest # Minimal (~280 MB)
```

### Building from source

Comment out the `image:` line and uncomment the `build:` section:

```yaml
services:
  clutch:
    # image: ghcr.io/adocampo/clutch:latest
    build:
      context: .
      dockerfile: Dockerfile            # Full Arch image
      # dockerfile: Dockerfile.minimal  # Scratch minimal image
```

Then:

```bash
docker compose build
docker compose up -d
```

```

---

## Volumes and mount points

| Container path | Purpose | Required |
|----------------|---------|----------|
| `/config` | Persistent state: SQLite database, logs, settings | Yes |
| `/media` | Media files (input/output). Map your libraries here | Yes |

### Examples

```bash
# Named volume for config, bind mount for media
-v clutch-config:/config \
-v /srv/media:/media

# Multiple media paths (use CLUTCH_ALLOW_ROOTS)
-v /movies:/movies \
-v /tvshows:/tvshows \
-e CLUTCH_ALLOW_ROOTS=/movies,/tvshows
```

The database is stored at `/config/service.db` by default. Back up this file to preserve your queue, users, settings, and history.

---

## Environment variables

All configuration is done through environment variables. When arguments are passed directly to the container (`docker run ... ghcr.io/adocampo/clutch --serve --workers 4`), environment variables are ignored and the arguments are forwarded as-is.

### Service configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CLUTCH_PORT` | `8765` | Port the HTTP service listens on |
| `CLUTCH_WORKERS` | `1` | Number of parallel conversion workers |
| `CLUTCH_GPUS` | *(none)* | Comma-separated NVENC GPU indices (e.g. `0` or `0,1`) |
| `CLUTCH_ALLOW_ROOTS` | `/media` | Comma-separated filesystem roots allowed for I/O |
| `CLUTCH_DEBUG` | `false` | Enable debug logging (`true` / `false`) |

### Watch directories

| Variable | Default | Description |
|----------|---------|-------------|
| `CLUTCH_WATCH_DIRS` | *(none)* | Comma-separated directories to watch for new files |
| `CLUTCH_WATCH_RECURSIVE` | `false` | Watch directories recursively |

### Scheduling

| Variable | Default | Description |
|----------|---------|-------------|
| `CLUTCH_SCHEDULE` | *(none)* | Schedule rule (e.g. `mon-fri 22:00-08:00`) |
| `CLUTCH_SCHEDULE_MODE` | *(none)* | `allow` or `block` |

### Price-based scheduling

| Variable | Default | Description |
|----------|---------|-------------|
| `CLUTCH_PRICE_PROVIDER` | *(none)* | `energy_charts` or `entsoe` |
| `CLUTCH_PRICE_COUNTRY` | *(none)* | Bidding zone code (e.g. `ES`, `DE-LU`, `FR`) |
| `CLUTCH_PRICE_LIMIT` | *(none)* | Max price in EUR/MWh to allow conversions |

---

## Ports

| Port | Protocol | Description |
|------|----------|-------------|
| `8765` | TCP | HTTP service (dashboard + API) |

---

## NVIDIA GPU support (NVENC)

To use NVENC hardware encoding inside Docker, you need:

1. The [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed on the host.
2. GPU passthrough configured in the container.

### docker run

```bash
docker run -d \
  --name clutch \
  --gpus all \
  -p 8765:8765 \
  -v clutch-config:/config \
  -v /srv/media:/media \
  -e CLUTCH_GPUS=0 \
  -e CLUTCH_WORKERS=2 \
  ghcr.io/adocampo/clutch:latest
```

### docker-compose.yml

```yaml
services:
  clutch:
    image: ghcr.io/adocampo/clutch:latest
    container_name: clutch
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - clutch-config:/config
      - /srv/media:/media
    environment:
      - CLUTCH_WORKERS=2
      - CLUTCH_GPUS=0,1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

volumes:
  clutch-config:
```

---

## Examples

### Basic service (CPU encoding)

```bash
docker run -d \
  --name clutch \
  -p 8765:8765 \
  -v clutch-config:/config \
  -v /home/user/Videos:/media \
  ghcr.io/adocampo/clutch:latest
```

### Multiple workers with GPU

```bash
docker run -d \
  --name clutch \
  --gpus all \
  -p 8765:8765 \
  -v clutch-config:/config \
  -v /srv/media:/media \
  -e CLUTCH_WORKERS=4 \
  -e CLUTCH_GPUS=0 \
  ghcr.io/adocampo/clutch:latest
```

### Watch a directory for new files

```bash
docker run -d \
  --name clutch \
  -p 8765:8765 \
  -v clutch-config:/config \
  -v /downloads:/downloads \
  -v /media:/media \
  -e CLUTCH_ALLOW_ROOTS=/downloads,/media \
  -e CLUTCH_WATCH_DIRS=/downloads \
  -e CLUTCH_WATCH_RECURSIVE=true \
  ghcr.io/adocampo/clutch:latest
```

### Schedule conversions at night (Spain electricity pricing)

```bash
docker run -d \
  --name clutch \
  -p 8765:8765 \
  -v clutch-config:/config \
  -v /srv/media:/media \
  -e CLUTCH_WORKERS=2 \
  -e CLUTCH_PRICE_PROVIDER=energy_charts \
  -e CLUTCH_PRICE_COUNTRY=ES \
  -e CLUTCH_PRICE_LIMIT=50 \
  ghcr.io/adocampo/clutch:latest
```

### Pass custom CLI arguments directly

```bash
docker run -d \
  --name clutch \
  -p 8765:8765 \
  -v clutch-config:/config \
  -v /srv/media:/media \
  ghcr.io/adocampo/clutch:latest \
  --serve --listen-host 0.0.0.0 --listen-port 8765 \
  --allow-root /media --workers 4 --gpus 0,1
```

When arguments are passed after the image name, the entrypoint ignores all `CLUTCH_*` environment variables and forwards the arguments directly to `clutch`.

---

## Health check

The service exposes `GET /api/status` which returns a JSON object with the service state. You can add a Docker health check:

```yaml
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/status')"]
      interval: 30s
      timeout: 10s
      retries: 3
```

---

## Updating

### Full image (`clutch`)

The full image supports two upgrade methods:

**Method 1: In-place upgrade (no restart needed)**

From the web dashboard, click the upgrade button when a new version is detected. This runs `pip install --upgrade` inside the running container. The upgrade persists until the container is recreated.

**Method 2: Pull new image (recommended for permanent upgrades)**

```bash
docker compose pull
docker compose up -d
```

### Minimal image (`clutch-minimal`)

The minimal image has no package manager, so in-place upgrades are not possible. Always pull or rebuild:

```bash
docker compose pull
docker compose up -d
```

Or with plain Docker:

```bash
docker pull ghcr.io/adocampo/clutch-minimal:latest
docker stop clutch && docker rm clutch
docker run -d ... ghcr.io/adocampo/clutch-minimal:latest
```

Your configuration and queue persist in the `/config` volume.

---

## Troubleshooting

### Container exits immediately

Check logs:

```bash
docker logs clutch
```

Common causes:

- Missing `/config` volume (permission denied on SQLite)
- Port 8765 already in use on the host

### HandBrakeCLI not found

This should not happen with either official image. If building locally, check that the Dockerfile completed successfully:

```bash
# Full image
docker run --rm ghcr.io/adocampo/clutch:latest HandBrakeCLI --version

# Minimal image (no shell, must invoke via ld-linux)
docker run --rm --entrypoint /usr/lib/ld-linux-x86-64.so.2 ghcr.io/adocampo/clutch-minimal:latest /usr/bin/HandBrakeCLI --version
```

### GPU not detected

Verify the NVIDIA Container Toolkit is working:

```bash
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

Then ensure `CLUTCH_GPUS` is set and the `deploy.resources.reservations.devices` section is present in your compose file.
