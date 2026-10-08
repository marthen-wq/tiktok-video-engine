"""Tes offline untuk sequencing multi-klip (hanya butuh ffmpeg + requests).

Jalankan dari root repo:  python3 -m unittest discover -s tests -v
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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

    def test_all_downloads_failing_aborts_the_run(self):
        # keputusan pemilik: tanpa footage sama sekali, run gagal agar baris Sheet tetap READY
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(generator, "TEMP_DIR", tmp), \
             mock.patch.object(generator, "CINEMATIC_VIDEO_SOURCES", ["https://example.test/a.webm", "https://example.test/b.webm"]), \
             mock.patch.object(generator, "download_clip", return_value=False):
            out = os.path.join(tmp, "bg.mp4")
            with self.assertRaises(RuntimeError):
                generator.prepare_background_video(20.0, out)
            self.assertFalse(os.path.exists(out))

    def test_one_failed_download_uses_fallback_segment_and_keeps_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.webm")
            make_clip(good, "blue", seconds=12)
            fetch = lambda url, dest: "bad" not in url and (subprocess.run(["cp", good, dest], check=True) or True)
            with mock.patch.object(generator, "TEMP_DIR", tmp), \
                 mock.patch.object(generator, "CINEMATIC_VIDEO_SOURCES", ["https://e.test/bad.webm", "https://e.test/ok.webm"]), \
                 mock.patch.object(generator, "download_clip", side_effect=fetch):
                out = os.path.join(tmp, "bg.mp4")
                generator.prepare_background_video(20.0, out)
            self.assertAlmostEqual(generator.probe_duration(out), 21.5, delta=0.3)


class ShortSegmentRegressionTest(unittest.TestCase):
    """Run Actions pertama: background 10,7 s padahal target 33,9 s (video diam ~22 s)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.patches = [mock.patch.object(generator, "TEMP_DIR", self.dir)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_remux_reports_real_duration_of_truncated_download(self):
        full = os.path.join(self.dir, "full.webm")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=60:r=25",
                        "-c:v", "libvpx", "-b:v", "2M", full], check=True, stderr=subprocess.DEVNULL)
        cut = os.path.join(self.dir, "cut.webm")
        with open(full, "rb") as src, open(cut, "wb") as dst:
            dst.write(src.read(os.path.getsize(full) // 4))
        self.assertGreater(generator.probe_duration(cut), 55)  # header masih mengaku 60 s
        clip = os.path.join(self.dir, "clip.mkv")
        self.assertTrue(generator.remux_clip(cut, clip))
        self.assertLess(generator.probe_duration(clip), 25)    # durasi nyata data yang terunduh

    def _clip(self, seconds=30):
        path = os.path.join(self.dir, "src.mkv")
        make_clip(path, "blue", seconds=seconds)
        return path

    def test_short_segment_from_random_start_is_redone_from_beginning(self):
        real_encode = generator.encode_segment

        def flaky(clip, start, seg_len, out, slow=1.0):  # titik acak menghasilkan segmen 2 s, seperti di runner
            real_encode(clip, start, 2.0 if start is not None else seg_len, out, slow)

        out = os.path.join(self.dir, "seg.mp4")
        with mock.patch.object(generator, "encode_segment", side_effect=flaky):
            self.assertTrue(generator.make_segment(self._clip(), 8.5, out))
        self.assertAlmostEqual(generator.probe_duration(out), 8.5, delta=0.15)

    def test_always_short_segments_mean_no_footage_and_abort(self):
        real_encode = generator.encode_segment
        clip_src = self._clip()
        with mock.patch.object(generator, "CINEMATIC_VIDEO_SOURCES", ["u/a", "u/b", "u/c"]), \
             mock.patch.object(generator, "download_clip",
                               side_effect=lambda u, d: subprocess.run(["cp", clip_src, d], check=True) or True), \
             mock.patch.object(generator, "encode_segment",
                               side_effect=lambda c, st, n, o, slow=1.0: real_encode(c, st, 2.0, o, slow)):
            with self.assertRaises(RuntimeError):
                generator.prepare_background_video(30.0, os.path.join(self.dir, "bg.mp4"))

    def test_clip_shorter_than_segment_is_slowed_down_not_looped(self):
        # merah 0-4 s lalu biru 4-5,9 s (seperti klip Rain 5,9 s di run #5)
        src = os.path.join(self.dir, "rain.mkv")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360:d=4:r=25",
                        "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=1.9:r=25",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", src],
                       check=True, stderr=subprocess.DEVNULL)
        out = os.path.join(self.dir, "seg.mp4")
        self.assertTrue(generator.make_segment(src, 9.1, out))
        self.assertAlmostEqual(generator.probe_duration(out), 9.1, delta=0.15)
        r, g, b = frame_rgb(out, 8.8)
        self.assertGreater(b, r)  # loop akan kembali ke merah di sini; slow-motion masih di bagian biru
        r0, _, b0 = frame_rgb(out, 0.5)
        self.assertGreater(r0, b0)

    def test_clip_far_too_short_still_loops(self):
        src = self._clip(seconds=3)
        out = os.path.join(self.dir, "seg.mp4")
        self.assertTrue(generator.make_segment(src, 9.1, out))  # 3,03x > MAX_SLOWDOWN: loop
        self.assertAlmostEqual(generator.probe_duration(out), 9.1, delta=0.15)

    def test_short_crossfade_result_is_extended_to_target(self):
        out = os.path.join(self.dir, "short.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=1080x1920:d=10:r=30",
                        "-pix_fmt", "yuv420p", out], check=True, stderr=subprocess.DEVNULL)
        generator.extend_to_duration(out, 33.9)
        self.assertAlmostEqual(generator.probe_duration(out), 33.9, delta=0.3)


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise generator.requests.HTTPError(f"{self.status_code} Client Error")

    def iter_content(self, chunk_size):
        yield self._body

    def close(self):
        pass


class DownloadRetryTest(unittest.TestCase):
    """Run Actions #3: Wikimedia membalas 429 untuk User-Agent generik."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        clip = os.path.join(self.tmp.name, "real.webm")
        make_clip(clip, "green", seconds=3)
        with open(clip, "rb") as fh:
            self.body = fh.read()
        generator._failed_urls.clear()
        self.sleep = mock.patch.object(generator.time, "sleep").start()

    def tearDown(self):
        mock.patch.stopall()
        generator._failed_urls.clear()
        self.tmp.cleanup()

    def test_retries_after_429_with_descriptive_user_agent(self):
        get = mock.patch.object(generator.requests, "get", side_effect=[
            FakeResponse(429, headers={"Retry-After": "5"}), FakeResponse(200, self.body)]).start()
        dest = os.path.join(self.tmp.name, "a.webm")
        self.assertTrue(generator.download_clip("https://upload.wikimedia.org/x/a.webm", dest))
        self.assertEqual(get.call_count, 2)
        self.sleep.assert_called_once_with(5.0)
        ua = get.call_args.kwargs["headers"]["User-Agent"]
        self.assertIn("github.com/marthen-wq/tiktok-video-engine", ua)
        self.assertNotIn("Mozilla", ua)

    def test_gives_up_after_attempts_and_does_not_retry_same_url_later(self):
        get = mock.patch.object(generator.requests, "get",
                                side_effect=lambda *a, **k: FakeResponse(429)).start()
        url = "https://upload.wikimedia.org/x/b.webm"
        self.assertFalse(generator.download_clip(url, os.path.join(self.tmp.name, "b.webm")))
        self.assertEqual(get.call_count, generator.DOWNLOAD_ATTEMPTS)
        self.assertFalse(generator.download_clip(url, os.path.join(self.tmp.name, "b2.webm")))
        self.assertEqual(get.call_count, generator.DOWNLOAD_ATTEMPTS)  # tidak ada permintaan tambahan
        self.assertTrue(all(w <= generator.MAX_RETRY_WAIT for (w,), _ in self.sleep.call_args_list))


class FootageCandidateTest(unittest.TestCase):
    """Run Actions #4: file asli 4K hanya memberi 0,9-2,4 s gambar per 15MB."""

    URL = "https://upload.wikimedia.org/wikipedia/commons/4/49/Nature_montage_around_Aberfeldy.webm"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        clip = os.path.join(self.tmp.name, "real.webm")
        make_clip(clip, "green", seconds=3)
        with open(clip, "rb") as fh:
            self.body = fh.read()
        generator._failed_urls.clear()
        mock.patch.object(generator.time, "sleep").start()

    def tearDown(self):
        mock.patch.stopall()
        generator._failed_urls.clear()
        self.tmp.cleanup()

    def test_transcodes_come_before_original(self):
        c = generator.footage_candidates(self.URL)
        self.assertEqual(c[0], "https://upload.wikimedia.org/wikipedia/commons/transcoded/4/49/"
                               "Nature_montage_around_Aberfeldy.webm/Nature_montage_around_Aberfeldy.webm.1080p.vp9.webm")
        self.assertEqual(c[-1], self.URL)
        self.assertEqual(generator.footage_candidates("https://example.com/a.mp4"), ["https://example.com/a.mp4"])

    def test_missing_transcodes_fall_through_to_original(self):
        def get(url, **kw):
            return FakeResponse(200, self.body) if url == self.URL else FakeResponse(404)
        g = mock.patch.object(generator.requests, "get", side_effect=get).start()
        self.assertTrue(generator.download_clip(self.URL, os.path.join(self.tmp.name, "o.webm")))
        self.assertEqual(g.call_count, len(generator.TRANSCODE_KEYS) + 1)

    def test_first_available_transcode_is_used(self):
        g = mock.patch.object(generator.requests, "get",
                              side_effect=lambda url, **kw: FakeResponse(200, self.body)).start()
        self.assertTrue(generator.download_clip(self.URL, os.path.join(self.tmp.name, "t.webm")))
        self.assertEqual(g.call_count, 1)
        self.assertIn("/transcoded/", g.call_args.args[0])

    def test_rate_limit_stops_trying_other_candidates(self):
        g = mock.patch.object(generator.requests, "get",
                              side_effect=lambda url, **kw: FakeResponse(429)).start()
        self.assertFalse(generator.download_clip(self.URL, os.path.join(self.tmp.name, "r.webm")))
        self.assertEqual(g.call_count, generator.DOWNLOAD_ATTEMPTS)  # hanya kandidat pertama


if __name__ == "__main__":
    unittest.main()
