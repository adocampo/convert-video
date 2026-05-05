# Clutch Wiki

Welcome to the detailed documentation for Clutch 2.0.

## What is Clutch?

Clutch is a video conversion tool built around HandBrakeCLI, with:

- Local CLI batch conversion
- Long-running HTTP service with queue and dashboard
- Remote job submission by path (`--server-url`)
- Remote file upload workflow (`--remote-server`)
- One-step stream conversion (`--stream`)

## Documentation map

- [CLI Options Reference](CLI-Options-Reference)
- [Service and API](Service-and-API)
- [Remote Upload and Stream Mode](Remote-Upload-and-Stream-Mode)
- [Scheduling and Energy Rules](Scheduling-and-Energy-Rules)
- [Docker](Docker)

## Typical workflows

### 1) Local recursive conversion

```bash
clutch --workers 2 --gpus 0,1 -r ~/Videos
```

### 2) Run shared service

```bash
clutch --serve --listen-host 0.0.0.0 --listen-port 8765 --allow-root /srv/media
```

### 3) Submit jobs by path to remote service

```bash
clutch --server-url http://server:8765 -o /srv/media/converted /srv/media/incoming/movie.mkv
```

### 4) Upload local files to remote service

```bash
clutch --remote-server server:8765 --upload-workers 4 --download -o ./converted ./input/*.mkv
```

### 5) One-step stream conversion

```bash
clutch --remote-server server:8765 --stream -o ./converted ./movie.mkv
```
