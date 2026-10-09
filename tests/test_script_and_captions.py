"""Tes offline untuk parser naskah, penyelarasan kata, dan teks kinetik (tanpa ffmpeg/jaringan).

Jalankan dari root repo:  python3 -m unittest discover -s tests -v
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import generator  # noqa: E402

SCRIPT = ("Get up. [pause] I know it *hurts*.\n\n"
          "This is not where you *break apart*. [long pause] This is where you harden.")


class ParseScriptTest(unittest.TestCase):
    def test_scenes_pauses_and_multiword_emphasis(self):
        scenes = generator.parse_script(SCRIPT)
        self.assertEqual(len(scenes), 2)
        first = scenes[0]
        self.assertEqual([w["text"] for w in first], ["Get", "up.", "I", "know", "it", "hurts."])
        self.assertEqual(first[1]["pause"], "short")
        self.assertEqual([w["emph"] for w in first], [False, False, False, False, False, True])
        second = scenes[1]
        emph = [w["text"] for w in second if w["emph"]]
        self.assertEqual(emph, ["break", "apart."])
        self.assertEqual(second[6]["pause"], "long")
        self.assertTrue(all(w["scene"] == 1 for w in second))

    def test_tts_text_flavors(self):
        scenes = generator.parse_script(SCRIPT)
        g = generator.tts_text(scenes, "gemini")
        self.assertIn("up. <short pause> I know it HURTS.", g)
        self.assertIn("BREAK APART. <long pause>", g)
        self.assertIn("\n\n", g)
        p = generator.tts_text(scenes, "plain")
        self.assertNotIn("<", p)
        self.assertIn("apart....", p)
        self.assertNotIn("*", p)

    def test_unknown_tags_are_ignored(self):
        scenes = generator.parse_script("Hello [whispers] world")
        self.assertEqual([w["text"] for w in scenes[0]], ["Hello", "world"])


class ParseJobTest(unittest.TestCase):
    def test_visual_lines_padded_and_unknown_style_defaults(self):
        job = generator.parse_job({"row": 7, "script": SCRIPT + "\n\nKeep going.", "visuals": "lion on rock",
                                   "style": "weird", "music_mood": "nope"})
        self.assertEqual(job["style"], generator.DEFAULT_STYLE)
        self.assertEqual(job["visuals"], ["lion on rock"] * 3)
        self.assertEqual(job["mood"], generator.STYLES[generator.DEFAULT_STYLE]["default_mood"])

    def test_extra_visual_lines_are_truncated(self):
        job = generator.parse_job({"script": "One.\n\nTwo.", "visuals": "a\nb\nc", "style": "soft_healing"})
        self.assertEqual(job["visuals"], ["a", "b"])
        self.assertEqual(job["cfg"]["voice"], "Sulafat")

    def test_empty_script_is_rejected(self):
        with self.assertRaises(ValueError):
            generator.parse_job({"script": "  "})


class AlignWordsTest(unittest.TestCase):
    def test_matched_words_take_asr_time_and_gaps_are_interpolated(self):
        script = ["Get", "up.", "I", "know", "it", "hurts."]
        asr = [("get", 0.5, 0.8), ("up", 0.8, 1.1), ("i", 2.0, 2.1), ("no", 2.1, 2.4),  # 'know' salah dengar
               ("it", 2.4, 2.5), ("hurts", 2.5, 3.0)]
        t = generator.align_words(script, asr, 4.0)
        self.assertEqual(t[0], (0.5, 0.8))
        self.assertEqual(t[5], (2.5, 3.0))
        self.assertGreaterEqual(t[3][0], 2.1 - 1e-9)   # interpolasi di antara 'I' dan 'it'
        self.assertLessEqual(t[3][1], 2.4 + 1e-9)

    def test_no_asr_spreads_over_duration(self):
        t = generator.align_words(["a", "b", "c"], [], 3.0)
        self.assertAlmostEqual(t[0][0], 0.0)
        self.assertAlmostEqual(t[-1][1], 3.0)


def timed_words(script, step=0.4, gap_after=None):
    """Kata dari parse_script dengan waktu buatan; gap_after={indeks: detik jeda tambahan}."""
    words = [w for s in generator.parse_script(script) for w in s]
    t = 0.5
    for i, w in enumerate(words):
        w["start"], w["end"] = t, t + step * 0.8
        t += step + (gap_after or {}).get(i, 0.0)
    return words


def dialogues(path):
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    out = []
    for m in re.finditer(r"Dialogue: 0,(\d+):(\d+):(\d+)\.(\d+),(\d+):(\d+):(\d+)\.(\d+),Default,,0,0,0,,(.*)", body):
        g = m.groups()
        t = lambda h, mi, s, cs: int(h) * 3600 + int(mi) * 60 + int(s) + int(cs) / 100
        out.append((t(*g[0:4]), t(*g[4:8]), g[8]))
    return body, out


class CaptionTest(unittest.TestCase):
    def _write(self, words, style):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.ass")
            generator.create_captions(words, style, path)
            return dialogues(path)

    def test_phrases_break_on_sentence_pause_and_scene(self):
        words = timed_words(SCRIPT)
        phrases = generator.group_phrases(words, 6)
        texts = [" ".join(w["text"] for w in p) for p in phrases]
        self.assertEqual(texts, ["Get up.", "I know it hurts.", "This is not where you break",
                                 "apart.", "This is where you harden."])

    def test_dark_words_light_up_when_spoken_and_emphasis_is_bigger(self):
        words = timed_words(SCRIPT)
        body, d = self._write(words, "dark_stoic")
        self.assertIn("Montserrat ExtraBold", body)
        start, _, text = d[1]                           # "I KNOW IT HURTS."
        self.assertIn("HURTS.", text)
        offsets = [int(x) for x in re.findall(r"\\t\((\d+),", text)]
        self.assertEqual(len(offsets), 4)
        self.assertEqual(offsets, sorted(offsets))      # kata menyala berurutan
        self.assertAlmostEqual(offsets[0] / 1000, words[2]["start"] - start, delta=0.011)
        self.assertIn("\\fscx125\\fscy125}HURTS.", text)
        for (_, e1, _), (s2, _, _) in zip(d, d[1:]):
            self.assertLessEqual(e1, s2 + 0.011)        # tidak tumpang-tindih

    def test_soft_shows_whole_phrase_with_slow_fade_and_italic_emphasis(self):
        body, d = self._write(timed_words(SCRIPT), "soft_healing")
        self.assertIn("Style: Default,Lora,", body)
        self.assertTrue(all(t.startswith("{\\fad(350,400)}") for _, _, t in d))
        self.assertIn("{\\i1}hurts.{\\i0}", d[1][2])
        self.assertNotIn("\\t(", body)

    def test_long_silence_blanks_screen(self):
        words = timed_words("One two three. Four five six.", gap_after={2: 4.0})
        _, d = self._write(words, "soft_healing")
        (_, e1, _), (s2, _, _) = d[0], d[1]
        self.assertLess(e1, s2 - 1.0)

    def test_braces_cannot_inject_ass_tags(self):
        _, d = self._write(timed_words("halo {\\an7} dunia"), "dark_stoic")
        visible = re.sub(r"\{\\[^}]*\}", "", d[0][2])
        self.assertNotIn("{", visible)
        self.assertNotIn("\\an7", visible)


if __name__ == "__main__":
    unittest.main()
