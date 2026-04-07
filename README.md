# History and why I did this

## convert-video

Usually, when you download from the internet movies and tv shows, you will have plenty of formats and codecs, and if the videos has some age, those codes will be quite unefficient (like AVC codec), occuping a lot of disk space when newer codecs (like AV1) are far more optimized (but not all players can play AV1 nowadays)

I have plenty of space in my home server, but I realized I could save 2/3 of it just by re-enconding all my videos.

At first, I used ffmpeg and when converting from AVC (or H264) to HVEC (or H265), and it saved almost the half of the space.

Then, I've tried AV1, but as I only have an NVidia RTX 3070, I must encode videos in AV1 with my CPU, instead of my GPU, which is a pain in the ass, to be sincere. Compression is awesome, sometimes even x6 times less than H264, and usually x2 time less than H265.

So far, so good, so, I began to do a simple script to automate this with ffpmeg, which all of us have almost preinstalled in our linux boxes.

### The good

But recently I've dowloaded a set of BDRip movies, like 60GB each, and even my script reduced them a lot, still were around 10GB, which I found pretty much for a 100 or 120 minutes movie. So I gave a try to handbrake and used its AV1 preset. The result was impressive: from 60GB in H264 to 2GB in AV1... x30 times less!!!

### The bad

Unfortunately, if you don't have a Nvidia 40X family, you cannot use your GPU to encode with AV1, so enconding a 2h movie will be around 2h with a decent i7 12th generation CPU... too much if you have hundreds of movies, and that doing if via network with your PC, your NAS probably will have a less powerful CPU and it will take a lot longer and probably will hung in the process.

### The ugly

At this point, I find marvelous the preset in HandBrake, how well optimized was and I realized those guys (HandBrake devs) know a lot better than me about encodings ad so, so I did try the H265 preset, and compared the result with my ffmpeg encoding in H265. The results were also astonishing. Handbrake H265 encoding was almost on par (a 15% or so higher) than AV1 when compressing from H264, and it even was able to compress HVEC videos even more!! (ffmpeg wasn't able to reduce a single bit of them). Besides, I can use my GPU and encode them with HVEC_NVENC codec, so compressing 1h of video can take just 4 minutes.

## Requisites

You only need to have installed [HandBrakeCLI](https://handbrake.fr/downloads2.php).
In order to use all the scripts without limitations, make sure to have installed all those:

- `mediainfo`
- `mkvpropedit`
- `pv` (optional, used by the bash version)

## Installation

### Quick install (automatic)

```bash
git clone https://github.com/adocampo/convert-video.git
cd convert-video
bash install.sh
```

The installer detects your OS and package manager, ensures Python 3.9+, venv, and pipx are available, installs `convert-video` via pipx, and checks for runtime dependencies.

### Manual install with pipx

```bash
pipx install git+https://github.com/adocampo/convert-video.git
```

### Manual install from local clone

```bash
git clone https://github.com/adocampo/convert-video.git
pipx install ./convert-video
```

### Verify installation

```bash
convert-video --version
```

## Development setup

If you want to contribute or test the latest development version:

```bash
git clone https://github.com/adocampo/convert-video.git
cd convert-video
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Inside the virtual environment, use the regular `convert-video` command:

```bash
convert-video --version
convert-video -r ~/Videos/
```

If your system also has `convert-video` installed through `pipx`, activate `.venv` before running it so the virtual environment version takes priority in `PATH`.

## Updating

### Self-update from the tool itself

```bash
# Check if a new version is available
convert-video --update

# Upgrade to the latest version
convert-video --upgrade
```

### Manual update with pipx

```bash
pipx install git+https://github.com/adocampo/convert-video.git --force
```

## Uninstalling

```bash
pipx uninstall convert-video
```

## Smart codec detection

`convert-video.py` automatically detects the current video codec and muxer before converting, avoiding unnecessary re-encodes:

### Codec quality hierarchy

The script understands that some codecs produce better compression than others:

```text
AVC (H.264) < HEVC (H.265) < AV1
```

- If the source is in a **worse** codec than the target (e.g. AVC → HEVC), it **converts** normally.
- If the source is already in a **better** codec than the target (e.g. AV1 → HEVC), it **skips** the file and warns you.
- If the source is in the **same** codec as the target, it checks the muxer (see below).

### Why HandBrake gets special treatment

I have experimented extensively with ffmpeg, mkvmerge, and HandBrake for video encoding. While all three can produce valid H.265/AV1 output, I have consistently achieved significantly better compression results using HandBrake's built-in presets compared to anything I could configure with ffmpeg or mkvmerge. The HandBrake team clearly knows a lot about encoding tuning and their presets are incredibly well optimized.

Because of this, the script treats the muxer as a quality signal:

- **Same codec + muxed by HandBrake** → The file is already optimally compressed. The script **skips** it with a message: `[SKIP] 'file.mkv' is already HEVC encoded by HandBrake. Use --force to override.`
- **Same codec + muxed by ffmpeg/mkvmerge/other** → The compression is likely suboptimal. The script shows a **warning** but **converts it anyway**: `[WARN] 'file.mkv' is already HEVC but was muxed by 'mkvmerge v88.0'. Converting anyway.`

Use `--force` to override this behavior and convert everything regardless.

## change-title

`change-title` is a quick script to change metadata title and make it match with its filename, so, intead of see something like
![image](https://github.com/user-attachments/assets/8d1019f0-e931-49cc-8770-2195a7e9ad17)
you will see this
![image](https://github.com/user-attachments/assets/ead048a4-79ae-47a6-a64f-60e8571709a5)

`change-title` can be used standalone as

```bash
change-title <video_name>
```

or recursively for all Matroska files like this

```bash
find . -type f -name "*.mkv" -print0 | xargs -0 -I {} change-title "{}"
```

## Usage

### Basic usage

Convert a single file:

```bash
convert-video movie.mp4
```

Convert and place output in a directory:

```bash
convert-video -o ~/converted/ movie.mp4
```

### Batch conversion

Convert all videos in a directory recursively:

```bash
convert-video -r ~/Videos/
```

Convert all `.mp4` files in a pattern (without subdirectories):

```bash
convert-video ~/Videos/*.mp4
```

Convert all videos and auto-find them:

```bash
convert-video --find  # Searches current directory
convert-video --find ~/Videos  # Searches ~/Videos directory pattern
```

Convert several files in parallel with local CLI workers:

```bash
convert-video --workers 3 -r ~/Videos/
```

Distribute NVENC jobs across two GPUs:

```bash
convert-video --workers 2 --gpus 0,1 -r ~/Videos/
```

With more than one local worker, the CLI switches to a combined progress display that keeps all active conversions in one coordinated terminal view. Raw verbose HandBrake output is disabled in that mode so the progress view stays readable.

When you pass `--gpus`, `convert-video` routes NVENC jobs through those GPU indices in round-robin order by passing `gpu=<index>` to HandBrake's NVENC encoder options. Leave it empty to let HandBrake choose the GPU automatically.

> **Note:** Multi-GPU support is implemented and ready to use, but has not been tested with actual multi-GPU hardware. If you have more than one NVENC-capable GPU, please report any issues you find.

### Service mode over the LAN

You can now run `convert-video` as a service on machine A and submit jobs from another machine in the LAN.

Important: in the first implementation, machine A must already be able to access the source and destination paths as normal filesystem paths. This works well with pre-mounted SMB or NFS shares. The service does not upload files from B to A and does not mount remote shares by itself.

Start the service on machine A:

```bash
convert-video --serve \
  --workers 2 \
  --gpus 0,1 \
  --listen-host 0.0.0.0 \
  --listen-port 8765 \
  --allow-root /mnt/media-b \
  --allow-root /srv/convert-output
```

Then open the browser from machine B and use the built-in dashboard:

```text
http://machine-a:8765/
```

The dashboard lets you:

- submit conversion jobs without using the CLI
- inspect queued, running, completed, skipped, and failed jobs
- cancel queued jobs
- review the service roots and watched directories exposed by machine A
- change how many workers run in parallel on the shared queue
- change which NVENC GPU indices the service rotates across
- change the default conversion settings used by the service and future watched files
- add and remove watched directories without restarting the service

Submit a job from machine B to be executed by machine A:

```bash
convert-video \
  --server-url http://machine-a:8765 \
  -o /mnt/media-b/converted \
  /mnt/media-b/incoming/movie.mkv
```

If you omit `-o`, the service keeps the current behavior and writes the converted output next to the source file.

Runtime service configuration is persisted in the service database (`--service-db`). This includes allowed roots, worker count, configured NVENC GPU indices, default job settings, and watched directories configured through the dashboard, so they survive service restarts. On first start, CLI service options seed that state; after that, the persisted state is restored from the database.

Service HTTP endpoints:

```text
GET    /
GET    /health
GET    /config
GET    /watchers
GET    /jobs
GET    /jobs/<job_id>
POST   /config
POST   /watchers
POST   /jobs
DELETE /watchers/<watcher_id>
DELETE /jobs/<job_id>
```

The service starts with 1 worker by default. You can raise the worker count from the dashboard to process several jobs in parallel; all workers share the same queue. If you configure NVENC GPU indices, the service assigns NVENC jobs to those GPUs in round-robin order.

### Automatic watched-directory mode

Machine A can also watch one or more directories and automatically enqueue any new video file that becomes stable on disk.

Watch a directory and convert everything that appears there:

```bash
convert-video --serve \
  --listen-host 0.0.0.0 \
  --watch-dir /mnt/media-b/watch \
  --watch-recursive \
  --watch-settle-time 60 \
  --allow-root /mnt/media-b
```

The watcher uses a polling strategy and waits until the file stops changing before queueing it, which helps avoid starting a conversion while a large file is still being copied.

When you use `--workers` in normal CLI mode, `convert-video` runs that many local conversions in parallel. In `--serve` mode, the same option seeds the service worker pool on first start for that service database; after that, the persisted worker count from the database takes precedence. When you use `--gpus`, local NVENC jobs rotate across those GPU indices, and `--serve --gpus ...` seeds the service's persisted NVENC GPU list on first start for that service database.

The configured GPU indices must be visible to the process running `convert-video`. If the service only sees GPU `0`, configuring `0,1` will not make GPU `1` usable until that second GPU is also exposed to HandBrake and NVENC on that machine.

### Advanced options

Convert with audio passthrough (no re-encoding audio):

```bash
convert-video -ap movie.mp4
```

Convert using AV1 codec with maximum compression (slow):

```bash
convert-video -c av1 -s movie.mp4
```

Auto-accept without prompts and delete source on success:

```bash
convert-video -y -ds movie.mkv
```

Power off after conversion completes:

```bash
convert-video -po movie.mp4
```

Force re-conversion even if file is already in target codec:

```bash
convert-video --force movie.mkv
```

Show source file information (codec, resolution, audio tracks, etc.):

```bash
convert-video -si movie.mkv
```

### ISO disc images

Convert a DVD/Blu-ray ISO image (automatically selects the main feature):

```bash
convert-video movie.iso
```

### Help

```bash
convert-video --help
```

Full help output:

```text
usage: convert-video [-h] [-o OUTPUT] [--find [PATTERN]] [-r] [-ds] [-c CODEC]
                     [-s] [-f] [-n] [-ap] [--force] [--gpus GPUS] [-y] [--verbose]
                     [-w WORKERS] [-po]
                     [--server-url SERVER_URL] [--serve]
                     [--listen-host LISTEN_HOST] [--listen-port LISTEN_PORT]
                     [--service-db SERVICE_DB] [--allow-root ALLOW_ROOT]
                     [--watch-dir WATCH_DIR] [--watch-recursive]
                     [--watch-poll-interval WATCH_POLL_INTERVAL]
                     [--watch-settle-time WATCH_SETTLE_TIME] [-si] [-v]
                     [--update] [--upgrade]
                     [input_files ...]

Convert video files using HandBrakeCLI and preserve all audio and subtitle
tracks.

options:
  -h, --help            show this help message and exit

input/output:
  input_files           Video files or directories to convert.
  -o, --output OUTPUT   Output directory for converted files.
  --find [PATTERN]      Recursively search for video files in directories
                        matching the pattern, or current directory if no
                        pattern is given.
  -r, --recursive       Recursively search directories for video files
                        matching the given patterns.
  -ds, --delete-source  Delete the original source file after a successful
                        conversion.

encoding:
  -c, --codec CODEC     Video codec: nvenc_h265 (default), nvenc_h264, av1,
                        x265.
  -s, --slow            Use slow encoding speed.
  -f, --fast            Use fast encoding speed.
  -n, --normal          Use normal encoding speed (default).
  -ap, --audio-passthrough
                        Pass through original audio tracks.
  --force               Force conversion even if file is already in the target
                        codec.
  --gpus GPUS           Comma-separated NVENC GPU indices to use. Example:
                        0,1 rotates jobs across GPU 0 and GPU 1.

behaviour:
  -y, --yes             Automatically accept transcoding without prompts.
  --verbose             Show verbose output from HandBrakeCLI.
  -w, --workers WORKERS
                        Number of local conversion workers to run in
                        parallel (default: 1).
  -po, --poweroff       Power off the system after conversion.
  --server-url SERVER_URL
                        Submit matching jobs to a remote convert-video
                        service instead of converting locally.

service:
  --serve               Run the HTTP conversion service on this machine.
  --listen-host LISTEN_HOST
                        Bind host for the service (default: 127.0.0.1).
  --listen-port LISTEN_PORT
                        Bind port for the service (default: 8765).
  --service-db SERVICE_DB
                        SQLite database path for the service queue.
  --allow-root ALLOW_ROOT
                        Allowed filesystem root for service input/output
                        paths. Repeat as needed.
  --watch-dir WATCH_DIR
                        Directory to watch and enqueue automatically when
                        running with --serve.
  --watch-recursive     Watch directories recursively when using --watch-dir.
  --watch-poll-interval WATCH_POLL_INTERVAL
                        Polling interval in seconds for watched directories.
  --watch-settle-time WATCH_SETTLE_TIME
                        Seconds a watched file must remain unchanged before
                        enqueueing.

info:
  -si, --source-info    Show source information about a single video file.
  -v, --version         show program's version number and exit
  --update              Check if a newer version is available on GitHub.
  --upgrade             Upgrade to the latest version from GitHub.
```
