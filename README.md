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

```
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

```
usage: convert-video [-h] [-o OUTPUT] [--find [PATTERN]] [-r] [-ds] [-c CODEC]
                     [-s] [-f] [-n] [-ap] [--force] [-y] [--verbose] [-po]
                     [-si] [-v] [--update] [--upgrade]
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

behaviour:
  -y, --yes             Automatically accept transcoding without prompts.
  --verbose             Show verbose output from HandBrakeCLI.
  -po, --poweroff       Power off the system after conversion.

info:
  -si, --source-info    Show source information about a single video file.
  -v, --version         show program's version number and exit
  --update              Check if a newer version is available on GitHub.
  --upgrade             Upgrade to the latest version from GitHub.
```

## change-title

`change-title` is a quick script to change metadata title and make it match with its filename, so, intead of see something like
![image](https://github.com/user-attachments/assets/8d1019f0-e931-49cc-8770-2195a7e9ad17)
you will see this
![image](https://github.com/user-attachments/assets/ead048a4-79ae-47a6-a64f-60e8571709a5)
