# Remote Upload and Stream Mode

This page explains the two remote execution models.

## Model A: Path-based remote jobs (`--server-url`)

Use this when the server can directly read source paths.

Example:

```bash
clutch --server-url http://server:8765 -o /srv/converted /srv/incoming/movie.mkv
```

## Model B: Upload-based remote jobs (`--remote-server`)

Use this when source files only exist on the client machine.

Example:

```bash
clutch \
  --remote-server server:8765 \
  --token YOUR_TOKEN \
  --upload-workers 4 \
  --download \
  -o ./converted \
  ./input/*.mkv
```

Flow:

1. Client uploads files to server upload directory.
2. Server enqueues conversion jobs.
3. Client polls job progress.
4. If `--download` is set, client downloads finished output.

## Stream convert mode (`--stream`)

Single request, one file at a time:

```bash
clutch --remote-server server:8765 --token YOUR_TOKEN --stream -o ./converted ./movie.mkv
```

Protocol behavior:

1. Client sends multipart upload.
2. Server runs conversion immediately.
3. Server streams NDJSON progress events.
4. Server appends final binary output in same response.

## Key flags

- `--remote-server`: upload workflow endpoint
- `--token`: auth token
- `--upload-workers`: parallel uploads
- `--download`: fetch output files automatically
- `--stream`: one-step upload/convert/download

## Mode compatibility

`--server-url` and `--remote-server` are mutually exclusive and should not be used together.
