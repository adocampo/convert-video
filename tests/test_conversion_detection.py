import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from convert_video.converter import find_existing_converted_output
from convert_video.mediainfo import check_already_converted


class CheckAlreadyConvertedTests(unittest.TestCase):
    def test_skips_handbrake_file_when_writing_application_is_present(self):
        data = {
            "media": {
                "track": [
                    {"@type": "General", "Writing_Application": "HandBrake 1.9.0"},
                    {"@type": "Video", "Format": "HEVC", "Encoded_Library": "x265"},
                ]
            }
        }

        with patch("convert_video.mediainfo.get_mediainfo_json", return_value=data):
            status = check_already_converted("episode.mkv", "nvenc_h265", False, quiet=True)

        self.assertEqual(status, "skip")

    def test_warns_same_codec_when_not_handbrake(self):
        data = {
            "media": {
                "track": [
                    {"@type": "General", "Encoded_Application": "mkvmerge v88.0"},
                    {"@type": "Video", "Format": "HEVC", "Encoded_Library_Name": "x265"},
                ]
            }
        }

        with patch("convert_video.mediainfo.get_mediainfo_json", return_value=data):
            status = check_already_converted("episode.mkv", "nvenc_h265", False, quiet=True)

        self.assertEqual(status, "warn")

    def test_force_bypasses_skip_logic(self):
        data = {
            "media": {
                "track": [
                    {"@type": "General", "Writing_Application": "HandBrake 1.9.0"},
                    {"@type": "Video", "Format": "HEVC", "Encoded_Library": "x265"},
                ]
            }
        }

        with patch("convert_video.mediainfo.get_mediainfo_json", return_value=data):
            status = check_already_converted("episode.mkv", "nvenc_h265", True, quiet=True)

        self.assertEqual(status, "convert")


class ExistingOutputDetectionTests(unittest.TestCase):
    def test_returns_existing_output_when_it_is_current_and_already_converted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "episode.mp4")
            output_path = os.path.join(temp_dir, "episode_converted.mkv")

            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("source")
            time.sleep(0.02)
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write("output")

            with patch("convert_video.converter.check_already_converted", return_value="skip"):
                existing = find_existing_converted_output(source_path, "", "nvenc_h265")

            self.assertEqual(existing, output_path)

    def test_ignores_existing_output_when_source_is_newer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "episode.mp4")
            output_path = os.path.join(temp_dir, "episode_converted.mkv")

            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("source")
            time.sleep(0.02)
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write("output")

            newer_time = os.path.getmtime(output_path) + 10
            os.utime(source_path, (newer_time, newer_time))

            with patch("convert_video.converter.check_already_converted", return_value="skip"):
                existing = find_existing_converted_output(source_path, "", "nvenc_h265")

            self.assertEqual(existing, "")


if __name__ == "__main__":
    unittest.main()