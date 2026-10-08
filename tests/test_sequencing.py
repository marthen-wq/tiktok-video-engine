"""Tes offline untuk sequencing multi-klip (hanya butuh ffmpeg + requests).

Jalankan dari root repo:  python3 -m unittest discover -s tests -v
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import generator  # noqa: E402


def make_clip(path, color, seconds=12, size="640x360"):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={seconds}:r=25",
                    "-c:v", "libvpx", "-b:v", "200k", path], check=True, stderr=subprocess.DEVNULL)


def frame_rgb(video, t):
    out = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", video, "-frames:v", "1",
         "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return tuple(out[:3])


class PlanSequenceTest(unittest.TestCase):
    def test_30s_video_gets_four_clips_and_exact_length(self):
        n, seg, xf, offsets = generator.plan_sequence(31.5)
        self.assertEqual(n, 4)
        self.assertEqual(len(offsets), 3)
        self.assertAlmostEqual(n * seg - (n - 1) * xf, 31.5, places=6)

    def test_clip_count_always_within_3_and_4(self):
        for total in (2, 8, 15, 20, 27, 31.5, 45, 90):
            n, seg, xf, _ = generator.plan_sequence(total)
            self.assertIn(n, (3, 4), total)
            self.assertGreater(seg, 2 * xf, total)
            self.assertAlmostEqual(n * seg - (n - 1) * xf, total, places=6)

    def test_no_two_consecutive_identical_urls(self):
        for _ in range(200):
            urls = generator.pick_clip_urls(4)
            self.assertEqual(len(urls), 4)
            for a, b in zip(urls, urls[1:]):
                self.assertNotEqual(a, b)


class RenderSequenceTest(unittest.TestCase):
    def test_background_has_distinct_clips_and_right_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            colors = {"red": "red", "green": "lime", "blue": "blue"}
            urls = []
            for name, col in colors.items():
                make_clip(os.path.join(tmp, f"{name}.webm"), col)
                urls.append(f"https://example.test/{name}.webm")

            generator.TEMP_DIR = tmp
            generator.CINEMATIC_VIDEO_SOURCES = urls
            # "unduhan" = salin klip lokal ke tujuan
            generator.download_clip = lambda url, dest: (
                subprocess.run(["cp", os.path.join(tmp, os.path.basename(url)), dest], check=True) or True)

            out = os.path.join(tmp, "bg.mp4")
            generator.prepare_background_video(30.0, out)

            self.assertAlmostEqual(generator.probe_duration(out), 31.5, delta=0.3)
            # titik tengah tiap segmen (tanpa crossfade) -> warna dominan harus berganti
            n, seg, xf, _ = generator.plan_sequence(31.5)
            dominant = []
            for i in range(n):
                t = i * (seg - xf) + seg / 2
                r, g, b = frame_rgb(out, t)
                dominant.append(max(("r", r), ("g", g), ("b", b), key=lambda x: x[1])[0])
            print("dominan per segmen:", dominant)
            self.assertEqual(len(dominant), 4)
            for a, b in zip(dominant, dominant[1:]):
                self.assertNotEqual(a, b)

            w_h = subprocess.check_output(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=p=0", out]).decode().strip()
            self.assertEqual(w_h, "1080,1920")

    def test_failed_download_uses_fallback_segment_and_keeps_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            generator.TEMP_DIR = tmp
            generator.CINEMATIC_VIDEO_SOURCES = ["https://example.test/a.webm", "https://example.test/b.webm"]
            generator.download_clip = lambda url, dest: False
            out = os.path.join(tmp, "bg.mp4")
            generator.prepare_background_video(20.0, out)
            self.assertAlmostEqual(generator.probe_duration(out), 21.5, delta=0.3)


if __name__ == "__main__":
    unittest.main()
