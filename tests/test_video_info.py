"""The plain-words description of a chosen video, and the warning for files that are too heavy to decode live."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "webapp"), str(ROOT / "host")]
import app as web
import stream_tx


def ffmpeg_says(video_line, audio=True, duration="00:02:07.45"):
    lines = ["Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':", f"  Duration: {duration}, start: 0.000000, bitrate: 1500 kb/s",
             f"  Stream #0:0[0x1](und): Video: {video_line}"]
    if audio:
        lines.append("  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 128 kb/s")
    return subprocess.CompletedProcess([], 0, "", "\n".join(lines) + "\n")


H264_1080 = "h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), 1920x1080 [SAR 1:1 DAR 16:9], 1500 kb/s, 29.97 fps, 29.97 tbr, 30k tbn (default)"


class VideoInfo(unittest.TestCase):
    def info(self, video_line, **kw):
        with patch.object(stream_tx.subprocess, "run", return_value=ffmpeg_says(video_line, **kw)):
            return stream_tx.video_info("clip.mp4")

    def test_a_normal_file_is_described_without_a_warning(self):
        info = self.info(H264_1080)                         # the hex tag 0x31637661 in the line must not be read as a size
        self.assertEqual(info["summary"], "1920×1080 · 29.97 fps · H.264 · 2:07 · with sound")
        self.assertEqual((info["heavy"], info["notes"]), ("", []))

    def test_big_or_fast_files_get_the_warning(self):
        big = self.info("hevc (Main), yuv420p, 3840x2160, 25 fps, 25 tbr")
        self.assertIn("bigger than 1080p", big["heavy"])
        fast = self.info("h264 (High), yuv420p, 1280x720, 60 fps, 60 tbr")
        self.assertIn("60 fps", fast["heavy"])
        self.assertIn("AV1", self.info("av1 (Main), yuv420p, 1280x720, 30 fps, 30 tbr")["heavy"])

    def test_a_vertical_phone_video_is_not_called_too_big(self):
        info = self.info("h264 (High), yuv420p, 720x1280, 30 fps, 30 tbr")
        self.assertEqual(info["heavy"], "")
        self.assertIn("black bars", " ".join(info["notes"]))

    def test_no_sound_and_long_files(self):
        info = self.info("h264 (High), yuv420p, 1280x720, 25 fps, 25 tbr", audio=False, duration="00:38:43.12")
        self.assertIn("38:43", info["summary"])
        self.assertTrue(info["summary"].endswith("no sound"))
        self.assertIn("silence", " ".join(info["notes"]))
        hours = self.info("h264, yuv420p, 1280x720, 25 fps", duration="01:05:09.00")
        self.assertIn("1:05:09", hours["summary"])

    def test_frame_rate_falls_back_to_tbr(self):
        info = self.info("mpeg4, yuv420p, 640x480, 25 tbr, 25 tbn")
        self.assertIn("25 fps", info["summary"])

    def test_cover_art_and_missing_video_are_refused(self):
        with patch.object(stream_tx.subprocess, "run", return_value=ffmpeg_says("mjpeg, yuvj420p, 600x600 (attached pic)")):
            with self.assertRaises(ValueError):
                stream_tx.video_info("song.mp3")
        with patch.object(stream_tx.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "no such file")):
            with self.assertRaises(ValueError):
                stream_tx.video_info("nope.mp4")

    def test_endpoint_only_describes_files_in_the_videos_folder(self):
        client = web.app.test_client()
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, "VIDEOS", Path(tmp)):
            (Path(tmp) / "clip.mp4").write_bytes(b"x")
            self.assertEqual(client.get("/api/video-info?name=../app.py").status_code, 404)
            self.assertEqual(client.get("/api/video-info?name=missing.mp4").status_code, 404)
            with patch.object(stream_tx.subprocess, "run", return_value=ffmpeg_says(H264_1080)):
                reply = client.get("/api/video-info?name=clip.mp4")
            self.assertEqual(reply.status_code, 200)
            self.assertIn("H.264", reply.get_json()["summary"])

    def test_twelve_bit_720p_is_not_called_heavy(self):
        # measured on the developer's PC: the 12-bit 720p sample film decodes at 26 times real time, so bit depth alone is no reason to warn
        info = self.info("hevc (Rext) (hvc1 / 0x31637668), yuv420p12le(tv, bt709), 1280x720, 24 fps, 24 tbr")
        self.assertEqual(info["heavy"], "")

    def test_the_warning_starts_with_heavy_file(self):
        self.assertTrue(self.info("hevc (Main), yuv420p, 3840x2160, 30 fps, 30 tbr")["heavy"].startswith("Heavy file"))

    def test_the_file_is_only_probed_never_decoded(self):
        # A long film must not be decoded just to read its stream list (a 13-minute file once timed out after 20 s):
        # no output file, so ffmpeg reads the headers and stops with exit code 1, which is expected and accepted.
        seen = []

        def fake(cmd, **kwargs):
            seen.append(cmd)
            result = ffmpeg_says(H264_1080)
            result.returncode = 1
            return result
        with patch.object(stream_tx.subprocess, "run", side_effect=fake):
            self.assertTrue(stream_tx.video_has_audio("long.mp4"))
            self.assertIn("1920", stream_tx.video_info("long.mp4")["summary"])
        for cmd in seen:
            self.assertNotIn("null", cmd)
            self.assertNotIn("-f", cmd)
            self.assertNotIn("-t", cmd)

    def test_the_popup_command_uses_an_encoder_the_package_has(self):
        page = web.app.test_client().get("/").data.decode()
        self.assertIn("-c:v libx265", page)
        self.assertNotIn("libx264", page)                   # the bundled ffmpeg has no H.264 encoder


if __name__ == "__main__":
    unittest.main()
