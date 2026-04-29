import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clutch import build_state_dir
from clutch.service import ConversionJob, ConversionService, JobStore
from clutch.converter import (
    find_existing_converted_output,
    _find_external_subtitles,
    _normalize_subtitle_language,
)
from clutch.mediainfo import check_already_converted


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

        with patch("clutch.mediainfo.get_mediainfo_json", return_value=data):
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

        with patch("clutch.mediainfo.get_mediainfo_json", return_value=data):
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

        with patch("clutch.mediainfo.get_mediainfo_json", return_value=data):
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

            with patch("clutch.converter.check_already_converted", return_value="skip"):
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

            with patch("clutch.converter.check_already_converted", return_value="skip"):
                existing = find_existing_converted_output(source_path, "", "nvenc_h265")

            self.assertEqual(existing, "")


class ExternalSubtitleDetectionTests(unittest.TestCase):
    def test_detects_same_basename_and_language_suffix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = os.path.join(temp_dir, "episode.mp4")
            with open(video, "w", encoding="utf-8") as handle:
                handle.write("video")

            subtitle_paths = [
                os.path.join(temp_dir, "episode.srt"),
                os.path.join(temp_dir, "episode.es.ass"),
                os.path.join(temp_dir, "episode.eng.vtt"),
            ]
            for path in subtitle_paths:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("sub")

            found = _find_external_subtitles(video)

            self.assertEqual(
                [(os.path.basename(path), lang) for path, lang in found],
                [
                    ("episode.eng.vtt", "eng"),
                    ("episode.es.ass", "spa"),
                    ("episode.srt", "und"),
                ],
            )

    def test_detects_language_suffix_with_underscore_separator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = os.path.join(temp_dir, "movie.mp4")
            with open(video, "w", encoding="utf-8") as handle:
                handle.write("video")

            subtitle_paths = [
                os.path.join(temp_dir, "movie_es.srt"),
                os.path.join(temp_dir, "movie_eng.ass"),
                os.path.join(temp_dir, "movie.srt"),
            ]
            for path in subtitle_paths:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("sub")

            found = _find_external_subtitles(video)

            self.assertEqual(
                [(os.path.basename(path), lang) for path, lang in found],
                [
                    ("movie.srt", "und"),
                    ("movie_eng.ass", "eng"),
                    ("movie_es.srt", "spa"),
                ],
            )

    def test_ignores_non_matching_or_invalid_suffix_patterns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = os.path.join(temp_dir, "movie.avi")
            with open(video, "w", encoding="utf-8") as handle:
                handle.write("video")

            noise = [
                "movie.en.us.srt",  # multiple dotted suffixes are invalid
                "movie_en_us.srt",  # multiple underscored suffixes are invalid
                "movie-extra.srt",  # different basename
                "movie.txt",        # unsupported extension
            ]
            for name in noise:
                with open(os.path.join(temp_dir, name), "w", encoding="utf-8") as handle:
                    handle.write("x")

            found = _find_external_subtitles(video)
            self.assertEqual(found, [])

    def test_prefers_idx_control_file_over_sub_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = os.path.join(temp_dir, "classic.mkv")
            with open(video, "w", encoding="utf-8") as handle:
                handle.write("video")

            idx_path = os.path.join(temp_dir, "classic.es.idx")
            sub_path = os.path.join(temp_dir, "classic.es.sub")
            with open(idx_path, "w", encoding="utf-8") as handle:
                handle.write("idx")
            with open(sub_path, "w", encoding="utf-8") as handle:
                handle.write("sub")

            found = _find_external_subtitles(video)

            self.assertEqual(len(found), 1)
            self.assertEqual(os.path.basename(found[0][0]), "classic.es.idx")
            self.assertEqual(found[0][1], "spa")

    def test_normalize_subtitle_language_defaults_to_und_for_unknown_tokens(self):
        self.assertEqual(_normalize_subtitle_language("es"), "spa")
        self.assertEqual(_normalize_subtitle_language("eng"), "eng")
        self.assertEqual(_normalize_subtitle_language("   "), "und")
        self.assertEqual(_normalize_subtitle_language("spanish"), "und")


class StateDirectoryMigrationTests(unittest.TestCase):
    def test_migrates_legacy_state_directory_to_clutch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_dir = os.path.join(temp_dir, "convert-video")
            branded_dir = os.path.join(temp_dir, "clutch")
            os.makedirs(legacy_dir, exist_ok=True)

            legacy_db = os.path.join(legacy_dir, "service.db")
            with open(legacy_db, "w", encoding="utf-8") as handle:
                handle.write("legacy-db")

            with patch.dict(os.environ, {"XDG_STATE_HOME": temp_dir}, clear=False):
                state_dir = build_state_dir()

            self.assertEqual(state_dir, branded_dir)
            self.assertTrue(os.path.exists(os.path.join(branded_dir, "service.db")))
            self.assertFalse(os.path.exists(legacy_db))

    def test_preserves_existing_branded_files_when_migrating_legacy_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_dir = os.path.join(temp_dir, "convert-video")
            branded_dir = os.path.join(temp_dir, "clutch")
            os.makedirs(legacy_dir, exist_ok=True)
            os.makedirs(branded_dir, exist_ok=True)

            with open(os.path.join(legacy_dir, "service.db"), "w", encoding="utf-8") as handle:
                handle.write("legacy-db")
            branded_state = os.path.join(branded_dir, "update-state.json")
            with open(branded_state, "w", encoding="utf-8") as handle:
                handle.write("current-state")

            with patch.dict(os.environ, {"XDG_STATE_HOME": temp_dir}, clear=False):
                state_dir = build_state_dir()

            self.assertEqual(state_dir, branded_dir)
            self.assertTrue(os.path.exists(os.path.join(branded_dir, "service.db")))
            with open(branded_state, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "current-state")


class JobStoreRecoveryTests(unittest.TestCase):
    def test_requeues_active_jobs_without_detached_runtime_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "service.db")
            input_path = os.path.join(temp_dir, "episode.mkv")

            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("video")

            store = JobStore(db_path)
            running = store.submit(ConversionJob(input_file=input_path))
            paused = store.submit(ConversionJob(input_file=input_path, output_dir=temp_dir))

            store.update_status(running["id"], "running", message="Encoding 37.0%")
            store.update_status(paused["id"], "paused", message="Paused manually.")

            reopened = JobStore(db_path)

            recovered_running = reopened.get(running["id"])
            recovered_paused = reopened.get(paused["id"])

            self.assertEqual(recovered_running["status"], "queued")
            self.assertEqual(recovered_paused["status"], "queued")
            self.assertEqual(recovered_running["progress_percent"], 0)
            self.assertEqual(recovered_paused["progress_percent"], 0)
            self.assertIn("Returned to queue from the beginning.", recovered_running["message"])
            self.assertIn("Returned to queue from the beginning.", recovered_paused["message"])

    def test_preserves_jobs_with_recoverable_runtime_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "service.db")
            input_path = os.path.join(temp_dir, "episode.mkv")

            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("video")

            store = JobStore(db_path)
            running = store.submit(ConversionJob(input_file=input_path))
            paused = store.submit(ConversionJob(input_file=input_path, output_dir=temp_dir))

            running_temp = os.path.join(temp_dir, "running.tmp.mkv")
            running_log = os.path.join(temp_dir, "running.log")
            running_final = os.path.join(temp_dir, "running.mkv")
            paused_temp = os.path.join(temp_dir, "paused.tmp.mkv")
            paused_log = os.path.join(temp_dir, "paused.log")
            paused_final = os.path.join(temp_dir, "paused.mkv")

            for path in (running_temp, running_log, paused_temp, paused_log):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("runtime")

            store.update_status(running["id"], "running", message="Encoding 37.0%")
            store.update_status(paused["id"], "paused", message="Paused for restart.")
            store.set_runtime(
                running["id"],
                process_id=os.getpid(),
                temp_file=running_temp,
                log_file=running_log,
                final_output_file=running_final,
                resume_on_start=False,
            )
            store.set_runtime(
                paused["id"],
                process_id=os.getpid(),
                temp_file=paused_temp,
                log_file=paused_log,
                final_output_file=paused_final,
                resume_on_start=True,
            )

            reopened = JobStore(db_path)

            recovered_running = reopened.get(running["id"])
            recovered_paused = reopened.get(paused["id"])

            self.assertEqual(recovered_running["status"], "running")
            self.assertEqual(recovered_paused["status"], "paused")
            self.assertEqual(int(recovered_running["process_id"]), os.getpid())
            self.assertEqual(int(recovered_paused["process_id"]), os.getpid())
            self.assertFalse(bool(recovered_running["resume_on_start"]))
            self.assertTrue(bool(recovered_paused["resume_on_start"]))


class ConversionServicePauseResumeTests(unittest.TestCase):
    def test_pause_resume_and_cancel_update_job_statuses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "service.db")
            input_path = os.path.join(temp_dir, "episode.mkv")

            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("video")

            service = ConversionService(db_path)
            record = service.submit_job(ConversionJob(input_file=input_path))
            claimed = service.store.claim_next()
            self.assertEqual(claimed["id"], record["id"])

            with service._job_control_lock:
                service._active_jobs[record["id"]] = 12345

            with patch("clutch.service.request_current_conversion_pause", return_value=True), \
                    patch("clutch.service.request_current_conversion_resume", return_value=True), \
                    patch("clutch.service.request_current_conversion_stop", return_value=True):
                paused = service.pause_job(record["id"])
                self.assertEqual(paused["status"], "paused")
                self.assertEqual(paused["message"], "Paused manually.")

                resumed = service.resume_job(record["id"])
                self.assertEqual(resumed["status"], "running")
                self.assertEqual(resumed["message"], "Resumed manually.")

                cancelled = service.cancel_job(record["id"])
                self.assertEqual(cancelled["status"], "cancelling")
                self.assertEqual(cancelled["message"], "Cancellation requested.")

    def test_resume_detached_paused_job_queues_recovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "service.db")
            input_path = os.path.join(temp_dir, "episode.mkv")
            temp_path = os.path.join(temp_dir, "episode.tmp.mkv")
            log_path = os.path.join(temp_dir, "episode.log")
            final_path = os.path.join(temp_dir, "episode.mkv.out")

            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("video")
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write("partial")
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write("Encoding: task 1 of 1, 42.00 %")

            service = ConversionService(db_path)
            record = service.submit_job(ConversionJob(input_file=input_path))
            service.store.update_status(record["id"], "paused", message="Paused manually.")
            service.store.set_runtime(
                record["id"],
                process_id=os.getpid(),
                temp_file=temp_path,
                log_file=log_path,
                final_output_file=final_path,
                resume_on_start=False,
            )

            resumed = service.resume_job(record["id"])

            self.assertEqual(resumed["status"], "running")
            self.assertTrue(bool(resumed["resume_on_start"]))
            self.assertIn("Waiting for a worker", resumed["message"])
            self.assertIn(record["id"], service._recoverable_job_ids)

    def test_stop_marks_running_job_for_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "service.db")
            input_path = os.path.join(temp_dir, "episode.mkv")
            temp_path = os.path.join(temp_dir, "episode.tmp.mkv")
            log_path = os.path.join(temp_dir, "episode.log")
            final_path = os.path.join(temp_dir, "episode.mkv.out")

            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("video")
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write("partial")
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write("Encoding: task 1 of 1, 42.00 %")

            service = ConversionService(db_path)
            record = service.submit_job(ConversionJob(input_file=input_path))
            claimed = service.store.claim_next()
            service.store.set_runtime(
                record["id"],
                process_id=os.getpid(),
                temp_file=temp_path,
                log_file=log_path,
                final_output_file=final_path,
                resume_on_start=False,
            )

            self.assertEqual(claimed["status"], "running")

            with service._job_control_lock:
                service._active_jobs[record["id"]] = 12345

            with patch("clutch.service.request_current_conversion_pause", return_value=True):
                service.stop()

            stopped = service.get_job(record["id"])
            self.assertEqual(stopped["status"], "paused")
            self.assertTrue(bool(stopped["resume_on_start"]))
            self.assertIn("will resume", stopped["message"])

    def test_prime_recoverable_jobs_collects_detached_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "service.db")
            input_path = os.path.join(temp_dir, "episode.mkv")
            temp_path = os.path.join(temp_dir, "episode.tmp.mkv")
            log_path = os.path.join(temp_dir, "episode.log")
            final_path = os.path.join(temp_dir, "episode.mkv.out")

            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("video")
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write("partial")
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write("Encoding: task 1 of 1, 42.00 %")

            service = ConversionService(db_path)
            record = service.submit_job(ConversionJob(input_file=input_path))
            service.store.update_status(record["id"], "paused", message="Paused for restart.")
            service.store.set_runtime(
                record["id"],
                process_id=os.getpid(),
                temp_file=temp_path,
                log_file=log_path,
                final_output_file=final_path,
                resume_on_start=True,
            )

            service._prime_recoverable_jobs()
            claimed = service._claim_recoverable_job()

            self.assertEqual(claimed["id"], record["id"])

    def test_clear_and_delete_preserve_active_jobs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "service.db")
            input_path = os.path.join(temp_dir, "episode.mkv")

            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("video")

            service = ConversionService(db_path)
            queued = service.submit_job(ConversionJob(input_file=input_path))
            paused = service.submit_job(ConversionJob(input_file=input_path, output_dir=temp_dir))

            service.store.update_status(paused["id"], "paused", message="Paused manually.")

            cleared = service.clear_jobs()

            self.assertEqual(cleared["deleted"], 1)
            self.assertEqual(cleared["paused"], 1)
            self.assertEqual(cleared["active"], 1)
            self.assertIsNone(service.get_job(queued["id"]))
            self.assertIsNotNone(service.get_job(paused["id"]))
            self.assertFalse(service.delete_job(paused["id"]))

    def test_watcher_ignore_treats_paused_job_as_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "service.db")
            input_path = os.path.join(temp_dir, "episode.mkv")

            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("video")

            service = ConversionService(db_path)
            service.submit_job(ConversionJob(input_file=input_path))
            latest = service.store.get_latest_for_input(input_path)
            service.store.update_status(latest["id"], "paused", message="Paused manually.")

            with patch("clutch.service.check_already_converted", return_value="convert"), \
                    patch("clutch.service.find_existing_converted_output", return_value=""):
                self.assertTrue(service.should_ignore_watch_path(input_path))


if __name__ == "__main__":
    unittest.main()