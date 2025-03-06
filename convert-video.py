import argparse
import subprocess
import os
import json
import re
import shutil
import tempfile
from typing import List
from tqdm import tqdm

# ANSI color codes
GREEN_COLOR = '\033[0;32m'
YELLOW_COLOR = '\033[1;33m'
RED_COLOR = '\033[0;31m'
RESET_COLOR = '\033[0m'
CYAN_COLOR = '\033[0;36m'


def info(msg: str):
    print(f"{GREEN_COLOR}{msg}{RESET_COLOR}")


def warning(msg: str):
    print(f"{YELLOW_COLOR}{msg}{RESET_COLOR}")


def error(msg: str):
    print(f"{RED_COLOR}{msg}{RESET_COLOR}")


def check_dependency(command: str):
    try:
        subprocess.run([command, '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        error(f"Error: {command} is required but not installed.")
        exit(1)


def get_resolution(filepath: str) -> str:
    try:
        result = subprocess.run(
            ["mediainfo", "--Inform=Video;%Width%x%Height%", filepath],
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        error(f"Error getting resolution for {filepath}: {e}")
        return ""


def get_audio_info(filepath: str) -> List[dict]:
    try:
        result = subprocess.run(
            ["mediainfo", "--Output=JSON", filepath],
            capture_output=True,
            check=True,
            text=True,
        )
        data = json.loads(result.stdout)
        audio_tracks = [
            track for track in data["media"]["track"] if track["@type"] == "Audio"
        ]
        return audio_tracks
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        error(f"Error getting audio info for {filepath}: {e}")
        return []


def generate_unique_filename(base_name: str, extension: str, output_path: str) -> str:
    counter = 1
    output_file = os.path.join(output_path, f"{base_name}.{extension}")
    while os.path.exists(output_file):
        match = re.search(r"\((\d+)\)$", base_name)
        if match:
            counter = int(match.group(1)) + 1
            base_name = base_name[:-len(match.group(0))]
        base_name += f" ({counter})"
        output_file = os.path.join(output_path, f"{base_name}.{extension}")
    return output_file


def convert_video(input_file: str, output_dir: str, codec: str, encode_speed: str, audio_passthrough: bool) -> bool:
    resolution = get_resolution(input_file)
    if not resolution:
        return False

    audio_params = []
    if audio_passthrough:
        audio_params = [
            "--audio-lang-list",
            "all",
            "--all-audio",
            "--audio-copy-mask",
            "eac3,ac3,aac,truehd,dts,dtshd,mp2,mp3,opus,vorbis,flac,alac",
            "--aencoder",
            "copy",
            "--audio-fallback",
            "none",
        ]
    else:
        audio_info = get_audio_info(input_file)
        if audio_info:
            for i, track in enumerate(audio_info):
                channels = int(track["Channels"])
                if channels == 2:
                    mix = "stereo"
                    br = 128
                elif channels in [6, 7]:
                    mix = "5point1"
                    br = 256
                elif channels == 8:
                    mix = "7point1"
                    br = 320
                else:
                    mix = "dpl2"
                    br = 160
                audio_params.extend([f"--audio={i+1}", f"--aencoder=opus", f"--ab={br}", f"--mixdown={mix}"])

        else:
            audio_params = ["--audio=1", "--aencoder=ac3", "--ab=256", "--mixdown=5point1"]


    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(input_file)[1], delete=False) as temp_file:
        temp_filepath = temp_file.name

    output_subdir = os.path.join(output_dir, os.path.dirname(os.path.relpath(input_file, os.getcwd())))
    os.makedirs(output_subdir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    extension = os.path.splitext(input_file)[1][1:]
    final_output = generate_unique_filename(base_name, extension, output_subdir)

    hb_params = [
        "HandBrakeCLI",
        "-i",
        input_file,
        "-o",
        temp_filepath,
        "--all-subtitles",
        "-f",
        "mkv",
    ] + audio_params

    if encode_speed == "slow":
        hb_params.extend(["--preset", "H.265 MKV 2160p60 4K"])
    elif encode_speed == "normal":
        hb_params.extend(["--preset", "H.265 NVENC 2160p 4K"])
    elif encode_speed == "fast":
        hb_params.extend(
            [
                "-e",
                codec,
                "-w",
                resolution.split("x")[0],
                "-l",
                resolution.split("x")[1],
                "-q",
                "30",
                "--vb",
                "1000",
            ]
        )

    try:
        with tqdm(total=100, desc=f"Converting {os.path.basename(input_file)}", unit="%", unit_scale=True) as pbar:
            process = subprocess.Popen(
                hb_params,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for line in iter(process.stdout.readline, ""):
                match = re.search(r"Encoding:.*? (\d+\.\d+)% \(.*? fps, avg .*? fps, ETA \S+\)", line)
                if match:
                    percent = float(match.group(1))
                    pbar.update(int(percent - pbar.n))

            process.wait()
            if process.returncode == 0:
                shutil.move(temp_filepath, final_output)
                info(f"Conversion successful: {final_output}")
                return True
            else:
                error(f"HandBrakeCLI returned an error: {process.stderr.read()}")
                os.remove(temp_filepath)
                return False
    except FileNotFoundError:
        error("HandBrakeCLI not found.")
        return False
    except subprocess.CalledProcessError as e:
        error(f"Error during conversion: {e}")
        os.remove(temp_filepath)
        return False

def main():
    check_dependency("HandBrakeCLI")
    check_dependency("mediainfo")

    parser = argparse.ArgumentParser(description="Convert video files using HandBrakeCLI.")
    parser.add_argument("input_files", nargs="+", help="Video files or directories to convert.")
    parser.add_argument("-o", "--output", default=".", help="Output directory (default: current directory).")
    parser.add_argument("-c", "--codec", default="nvenc_h265", help="Video codec (default: nvenc_h265).")
    parser.add_argument(
        "-s", "--speed", choices=["slow", "normal", "fast"], default="normal", help="Encoding speed (default: normal)."
    )
    parser.add_argument("-ap", "--audio-passthrough", action="store_true", help="Pass through original audio tracks.")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recursively search directories for video files.")
    args = parser.parse_args()

    input_files = []
    for item in args.input_files:
        if os.path.isdir(item):
            if args.recursive:
                for root, _, files in os.walk(item):
                    for file in files:
                        if file.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.ts')):
                            input_files.append(os.path.join(root, file))
            else:
                warning(f"Directory {item} provided without -r flag. Skipping.")
        elif os.path.isfile(item):
            input_files.append(item)
        else:
            warning(f"Invalid input: {item}")

    if not input_files:
        error("No valid video files found.")
        exit(1)

    os.makedirs(args.output, exist_ok=True)

    for input_file in input_files:
        if convert_video(input_file, args.output, args.codec, args.speed, args.audio_passthrough):
            pass  #success
        else:
            warning(f"Conversion failed for: {input_file}")

if __name__ == "__main__":
    main()
