"""Tes offline untuk penyusunan footage per adegan (hanya butuh ffmpeg + requests).

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


class PlanShotsTest(unittest.TestCase):
    def test_long_scene_is_split_and_total_survives_crossfade(self):
        spans = [(0.0, 4.0), (4.0, 17.0), (17.0, 24.0)]
        shots, xf = generator.plan_shots(spans, 0.6)
        self.assertEqual([s["scene"] for s in shots], [0, 1, 1, 2])
        self.assertAlmostEqual(sum(s["len"] for s in shots) - (len(shots) - 1) * xf, 24.0, places=6)

    def test_crossfade_shrinks_for_very_short_shots(self):
        shots, xf = generator.plan_shots([(0.0, 1.2), (1.2, 8.0)], 0.8)
        self.assertLessEqual(xf, 1.2 / 3 + 1e-9)


class RenderScenesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        mock.patch.object(generator, "TEMP_DIR", self.dir).start()

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def _job(self, visuals):
        return {"cfg": dict(generator.STYLES["soft_healing"], grade="null"), "visuals": visuals}

    def test_each_scene_uses_its_own_footage_and_length_matches(self):
        clips = {}
        for name, col in {"red": "red", "blue": "blue"}.items():
            clips[name] = os.path.join(self.dir, f"{name}.webm")
            make_clip(clips[name], col)
        search = lambda q: [{"id": q, "kind": "video", "url": clips[q], "credit": f"{q} (Pexels)"}]
        mock.patch.object(generator, "search_footage", side_effect=search).start()
        mock.patch.object(generator, "download_clip",
                          side_effect=lambda u, d: subprocess.run(["cp", u, d], check=True) or True).start()
        out = os.path.join(self.dir, "bg.mp4")
        credits = generator.prepare_scene_video(self._job(["red", "blue"]), [(0.0, 5.0), (5.0, 10.0)], out)
        self.assertAlmostEqual(generator.probe_duration(out), 10.0, delta=0.2)
        r, _, b = frame_rgb(out, 2.0)
        self.assertGreater(r, b)                      # adegan 1: merah
        r, _, b = frame_rgb(out, 8.0)
        self.assertGreater(b, r)                      # adegan 2: biru
        self.assertEqual(credits, ["blue (Pexels)", "red (Pexels)"])

    def test_failed_footage_falls_back_and_keeps_length(self):
        mock.patch.object(generator, "search_footage", return_value=[]).start()
        out = os.path.join(self.dir, "bg.mp4")
        credits = generator.prepare_scene_video(self._job(["nothing"]), [(0.0, 7.5)], out)
        self.assertAlmostEqual(generator.probe_duration(out), 7.5, delta=0.2)
        self.assertEqual(credits, [])


class ShortSegmentRegressionTest(unittest.TestCase):
    """Run Actions pertama: background 10,7 s padahal target 33,9 s (video diam ~22 s)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        mock.patch.object(generator, "TEMP_DIR", self.dir).start()

    def tearDown(self):
        mock.patch.stopall()
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

        def flaky(clip, start, seg_len, out, vf):  # titik acak menghasilkan segmen 2 s, seperti di runner
            real_encode(clip, start, 2.0 if start is not None else seg_len, out, vf)

        out = os.path.join(self.dir, "seg.mp4")
        with mock.patch.object(generator, "encode_segment", side_effect=flaky):
            self.assertTrue(generator.make_segment(self._clip(), 8.5, out))
        self.assertAlmostEqual(generator.probe_duration(out), 8.5, delta=0.15)

    def test_short_clip_is_slowed_down_instead_of_looped_when_close(self):
        seen = []
        real_encode = generator.encode_segment
        with mock.patch.object(generator, "encode_segment",
                               side_effect=lambda c, st, n, o, vf: seen.append(vf) or real_encode(c, st, n, o, vf)):
            out = os.path.join(self.dir, "slow.mp4")
            self.assertTrue(generator.make_segment(self._clip(seconds=5), 6.5, out))
        self.assertIn("setpts=", seen[0])
        self.assertAlmostEqual(generator.probe_duration(out), 6.5, delta=0.15)

    def test_short_crossfade_result_is_extended_to_target(self):
        out = os.path.join(self.dir, "short.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=1080x1920:d=10:r=30",
                        "-pix_fmt", "yuv420p", out], check=True, stderr=subprocess.DEVNULL)
        generator.extend_to_duration(out, 33.9)
        self.assertAlmostEqual(generator.probe_duration(out), 33.9, delta=0.3)


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def iter_content(self, chunk_size):
        yield self._body

    def close(self):
        pass


class DownloadRetryTest(unittest.TestCase):
    """Run Actions #3: CDN membalas 429 untuk User-Agent generik."""

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
        self.assertTrue(generator.download_clip("https://videos.pexels.com/x/a.mp4", dest))
        self.assertEqual(get.call_count, 2)
        self.sleep.assert_called_once_with(5.0)
        ua = get.call_args.kwargs["headers"]["User-Agent"]
        self.assertIn("github.com/marthen-wq/tiktok-video-engine", ua)
        self.assertNotIn("Mozilla", ua)

    def test_gives_up_after_attempts_and_does_not_retry_same_url_later(self):
        get = mock.patch.object(generator.requests, "get",
                                side_effect=lambda *a, **k: FakeResponse(429)).start()
        url = "https://videos.pexels.com/x/b.mp4"
        self.assertFalse(generator.download_clip(url, os.path.join(self.tmp.name, "b.webm")))
        self.assertEqual(get.call_count, generator.DOWNLOAD_ATTEMPTS)
        self.assertFalse(generator.download_clip(url, os.path.join(self.tmp.name, "b2.webm")))
        self.assertEqual(get.call_count, generator.DOWNLOAD_ATTEMPTS)  # tidak ada permintaan tambahan
        self.assertTrue(all(w <= generator.MAX_RETRY_WAIT for (w,), _ in self.sleep.call_args_list))


class SearchFootageTest(unittest.TestCase):
    def tearDown(self):
        mock.patch.stopall()

    def test_portrait_hd_pexels_file_is_picked_and_photos_come_last(self):
        videos = {"videos": [{"id": 7, "user": {"name": "Ann"}, "video_files": [
            {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "land"},
            {"file_type": "video/mp4", "width": 720, "height": 1280, "link": "p720"},
            {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "p1080"}]}]}
        photos = {"photos": [{"id": 9, "photographer": "Bo", "src": {"large2x": "img"}}]}

        def get(url, **kw):
            body = videos if "videos" in url else photos
            return mock.Mock(json=lambda: body)
        mock.patch.object(generator, "PEXELS_API_KEY", "k").start()
        mock.patch.object(generator, "PIXABAY_API_KEY", "").start()
        mock.patch.object(generator.requests, "get", side_effect=get).start()
        c = generator.search_footage("lion on rock")
        self.assertEqual([x["url"] for x in c], ["p1080", "img"])
        self.assertEqual(c[0]["credit"], "Ann (Pexels)")


if __name__ == "__main__":
    unittest.main()
