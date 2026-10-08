"""Tes offline: footage dipilih sesuai isi narasi (tanpa jaringan).

Jalankan dari root repo:  python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import generator  # noqa: E402

QUOTE = ("Kamu tidak sedang tertinggal. Kamu hanya sedang ditempa di ruang yang tidak dilihat orang. "
         "Setiap pagi yang kamu mulai dengan berat, setiap malam yang kamu tutup dengan lelah, semuanya "
         "sedang membentuk dirimu. Berhenti membandingkan langkah awalmu dengan panggung orang lain. "
         "Mereka juga pernah berada di titik nol, ragu, dan hampir menyerah. Bedanya, mereka memilih "
         "untuk tetap berjalan. Jadi pelan pun tidak apa-apa, asal jangan berhenti. Waktumu akan datang.")
C = "https://upload.wikimedia.org/wikipedia/commons/"


class SceneMatchingTest(unittest.TestCase):
    def test_roots_match_with_indonesian_prefixes_only_at_word_start(self):
        self.assertEqual(generator.scenes_in_text("Melangkah mendaki puncak"), ["walking", "mountain"])
        self.assertEqual(generator.scenes_in_text("lapisan sampai apa-apa"), [])  # bukan "api"
        self.assertEqual(generator.scenes_in_text("semangat yang membara"), ["fire"])  # satu adegan, tidak ganda

    def test_scenes_keep_order_of_appearance(self):
        self.assertEqual(generator.scenes_in_text("berjalan di bawah hujan sampai pagi"),
                         ["walking", "rain", "sunrise"])

    def test_each_segment_gets_the_words_spoken_while_it_is_on_screen(self):
        timings = generator.spread_words(QUOTE.split(), 0.5, 32.4)
        n, seg, xf, _ = generator.plan_sequence(33.9)
        texts = generator.segment_texts(timings, n, seg, xf)
        self.assertEqual(len(texts), 4)
        self.assertIn("ditempa", texts[0])
        self.assertIn("panggung", texts[2])
        self.assertIn("berjalan", texts[3])
        self.assertEqual(generator.scenes_in_text(texts[0])[0], "blacksmith forging")


class CommonsSearchTest(unittest.TestCase):
    def test_parses_api_response_and_keeps_only_usable_videos(self):
        payload = {"query": {"pages": {
            "3": {"index": 2, "imageinfo": [{"url": C + "a/ab/Forge2.webm", "mediatype": "VIDEO", "width": 1920}]},
            "1": {"index": 1, "imageinfo": [{"url": C + "c/cd/Forge1.webm", "mediatype": "VIDEO", "width": 1280}]},
            "2": {"index": 3, "imageinfo": [{"url": C + "e/ef/Tiny.webm", "mediatype": "VIDEO", "width": 320}]},
            "4": {"index": 4, "imageinfo": [{"url": C + "1/12/Photo.jpg", "mediatype": "BITMAP", "width": 4000}]},
        }}}
        resp = mock.Mock(status_code=200)
        resp.json.return_value = payload
        with mock.patch.object(generator.requests, "get", return_value=resp) as get:
            urls = generator.search_commons_videos("blacksmith forging")
        self.assertEqual(urls, [C + "c/cd/Forge1.webm", C + "a/ab/Forge2.webm"])  # urutan relevansi
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["gsrsearch"], "filetype:video blacksmith forging")
        self.assertIn("github.com/marthen-wq", get.call_args.kwargs["headers"]["User-Agent"])

    def test_search_failure_returns_empty_list(self):
        with mock.patch.object(generator.requests, "get", side_effect=generator.requests.ConnectionError("x")):
            self.assertEqual(generator.search_commons_videos("rain"), [])


class PlanClipSourcesTest(unittest.TestCase):
    def setUp(self):
        self.timings = generator.spread_words(QUOTE.split(), 0.5, 32.4)
        self.n, self.seg, self.xf, _ = generator.plan_sequence(33.9)

    def test_segments_get_footage_for_their_own_narration_without_repeats(self):
        library = {term: [f"{C}x/{term.replace(' ', '_')}_{k}.webm" for k in range(3)]
                   for _, term in generator.SCENE_KEYWORDS}
        with mock.patch.object(generator, "search_commons_videos", side_effect=lambda t: library[t]):
            picks = generator.plan_clip_sources(self.n, self.seg, self.xf, self.timings)
        self.assertEqual(len(picks), 4)
        self.assertEqual(len(set(picks)), 4)
        self.assertIn("blacksmith_forging", picks[0])  # "ditempa" diucapkan di segmen 1

    def test_scene_without_results_moves_to_next_scene_from_the_narration(self):
        def search(term):
            return [] if term == "blacksmith forging" else [f"{C}x/{term.replace(' ', '_')}.webm"]
        with mock.patch.object(generator, "search_commons_videos", side_effect=search):
            picks = generator.plan_clip_sources(self.n, self.seg, self.xf, self.timings)
        self.assertIn("empty_road", picks[0])  # adegan berikutnya di segmen yang sama ("ruang ... tidak dilihat")

    def test_no_results_anywhere_falls_back_to_pool(self):
        with mock.patch.object(generator, "search_commons_videos", return_value=[]):
            picks = generator.plan_clip_sources(self.n, self.seg, self.xf, self.timings)
        self.assertTrue(all(p in generator.CINEMATIC_VIDEO_SOURCES for p in picks))

    def test_each_scene_is_searched_once(self):
        with mock.patch.object(generator, "search_commons_videos", return_value=[]) as search:
            generator.plan_clip_sources(self.n, self.seg, self.xf, self.timings)
        terms = [c.args[0] for c in search.call_args_list]
        self.assertEqual(len(terms), len(set(terms)))


if __name__ == "__main__":
    unittest.main()
