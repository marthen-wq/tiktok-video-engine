"""Tes offline untuk sinkronisasi subtitle dan ducking audio (butuh ffmpeg).

Jalankan dari root repo:  python3 -m unittest discover -s tests -v
"""
import asyncio
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import generator  # noqa: E402

TEXT = "Kamu tidak sedang tertinggal, kamu hanya sedang ditempa. Teruslah melangkah dengan sabar."


def word_events(words, step=0.5, start=0.4):
    return [{"kind": "WordBoundary", "text": w.strip(",."), "start": start + i * step,
             "end": start + i * step + step * 0.8} for i, w in enumerate(words)]


def parse_dialogues(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    for line in lines:
        m = re.match(r"Dialogue: 0,(\d+):(\d+):(\d+)\.(\d+),(\d+):(\d+):(\d+)\.(\d+),Default,,0,0,0,,(.*)", line)
        if m:
            g = m.groups()
            t = lambda h, mi, s, cs: int(h) * 3600 + int(mi) * 60 + int(s) + int(cs) / 100
            out.append((t(*g[0:4]), t(*g[4:8]), g[8].strip()))
    return out


class WordTimingTest(unittest.TestCase):
    def test_word_boundary_events_drive_timing_and_keep_punctuation(self):
        words = TEXT.split()
        t = generator.build_word_timings(TEXT, word_events(words), 12.0)
        self.assertEqual([w for w, _, _ in t], words)  # tanda baca asli terjaga
        self.assertAlmostEqual(t[0][1], 0.4)
        self.assertAlmostEqual(t[3][1], 0.4 + 3 * 0.5)

    def test_word_boundary_count_mismatch_uses_event_text(self):
        ev = word_events(["Kamu", "tidak", "sedang"])
        t = generator.build_word_timings(TEXT, ev, 12.0)
        self.assertEqual([w for w, _, _ in t], ["Kamu", "tidak", "sedang"])

    def test_sentence_boundary_splits_words_inside_each_sentence(self):
        ev = [{"kind": "SentenceBoundary", "text": "Kamu tidak sedang tertinggal, kamu hanya sedang ditempa.",
               "start": 0.5, "end": 4.5},
              {"kind": "SentenceBoundary", "text": "Teruslah melangkah dengan sabar.", "start": 6.0, "end": 8.0}]
        t = generator.build_word_timings(TEXT, ev, 9.0)
        self.assertEqual(len(t), len(TEXT.split()))
        self.assertAlmostEqual(t[0][1], 0.5)
        self.assertAlmostEqual(t[7][2], 4.5)       # kata terakhir kalimat 1 berakhir tepat di batas kalimat
        self.assertAlmostEqual(t[8][1], 6.0)       # kalimat 2 mulai setelah jeda 1,5 detik
        self.assertAlmostEqual(t[-1][2], 8.0)

    def test_no_events_falls_back_to_proportional_and_covers_duration(self):
        t = generator.build_word_timings(TEXT, [], 10.0)
        self.assertEqual(len(t), len(TEXT.split()))
        self.assertAlmostEqual(t[0][1], 0.0)
        self.assertAlmostEqual(t[-1][2], 10.0)
        for (_, s1, e1), (_, s2, _) in zip(t, t[1:]):
            self.assertLessEqual(s1, e1)
            self.assertAlmostEqual(e1, s2)
        # kata panjang mendapat waktu lebih lama dari kata pendek
        dur = {w: e - s for w, s, e in t}
        self.assertGreater(dur["tertinggal,"], dur["kamu"])


class AssSubtitleTest(unittest.TestCase):
    def test_chunks_start_when_first_word_is_spoken(self):
        words = TEXT.split()
        ev = word_events(words)
        with tempfile.TemporaryDirectory() as tmp:
            ass = os.path.join(tmp, "s.ass")
            generator.create_ass_subtitles(TEXT, 12.0, ass, ev)
            d = parse_dialogues(ass)
        self.assertEqual(len(d), -(-len(words) // 3))
        for i, (start, end, text) in enumerate(d):
            self.assertAlmostEqual(start, ev[i * 3]["start"], delta=0.011)
            self.assertLess(start, end)
            self.assertEqual(text, " ".join(words[i * 3:i * 3 + 3]).upper())
        for (_, e1, _), (s2, _, _) in zip(d, d[1:]):
            self.assertLessEqual(e1, s2 + 0.011)  # tidak ada tumpang-tindih

    def test_long_pause_blanks_screen_but_short_pause_does_not(self):
        ev = [{"kind": "WordBoundary", "text": w, "start": s, "end": s + 0.3}
              for w, s in [("a", 0.0), ("b", 0.4), ("c", 0.8), ("d", 5.0), ("e", 5.4), ("f", 5.8)]]
        with tempfile.TemporaryDirectory() as tmp:
            ass = os.path.join(tmp, "s.ass")
            generator.create_ass_subtitles("a b c d e f", 7.0, ass, ev)
            d = parse_dialogues(ass)
        (s1, e1, _), (s2, _, _) = d[0], d[1]
        self.assertLess(e1, s2 - 1.0)  # jeda ~3,9 detik: layar kosong, subtitle tidak menggantung

    def test_braces_in_quote_cannot_inject_ass_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            ass = os.path.join(tmp, "s.ass")
            generator.create_ass_subtitles("halo {\\an7} dunia", 3.0, ass, None)
            with open(ass, encoding="utf-8") as fh:
                body = fh.read().split("[Events]")[1]
        self.assertNotIn("{", body)


class NarrationEventsTest(unittest.TestCase):
    def _fake_edge_tts(self, accept_boundary=True):
        chunks = [
            {"type": "audio", "data": b"AAA"},
            {"type": "WordBoundary", "offset": 5_000_000, "duration": 3_000_000, "text": "Kamu"},
            {"type": "audio", "data": b"BBB"},
            {"type": "SentenceBoundary", "offset": 0, "duration": 20_000_000, "text": "Kamu."},
        ]

        class Communicate:
            seen = {}

            def __init__(self, text, voice, rate, pitch, **kw):
                if kw and not accept_boundary:
                    raise TypeError("unexpected keyword 'boundary'")
                Communicate.seen = kw

            async def stream(self):
                for c in chunks:
                    yield c

        mod = types.ModuleType("edge_tts")
        mod.Communicate = Communicate
        return mod

    def test_events_are_converted_from_ticks_to_seconds(self):
        sys.modules["edge_tts"] = self._fake_edge_tts()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "n.mp3")
                events = asyncio.run(generator.generate_narration("Kamu.", out))
                with open(out, "rb") as fh:
                    self.assertEqual(fh.read(), b"AAABBB")
            self.assertEqual(sys.modules["edge_tts"].Communicate.seen, {"boundary": "WordBoundary"})
        finally:
            del sys.modules["edge_tts"]
        self.assertEqual(events[0], {"kind": "WordBoundary", "text": "Kamu", "start": 0.5, "end": 0.8})
        self.assertEqual(events[1]["end"], 2.0)

    def test_old_edge_tts_without_boundary_param_still_works(self):
        sys.modules["edge_tts"] = self._fake_edge_tts(accept_boundary=False)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                events = asyncio.run(generator.generate_narration("Kamu.", os.path.join(tmp, "n.mp3")))
        finally:
            del sys.modules["edge_tts"]
        self.assertEqual(len(events), 2)


def mean_db(path, start, length, filters):
    """Level rata-rata (dB) pada jendela waktu setelah filter pita frekuensi."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", path,
                        "-af", f"{filters},volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr).group(1))


class DuckingTest(unittest.TestCase):
    def test_music_drops_while_narrator_speaks_and_narration_stays_full(self):
        low = "lowpass=f=300,lowpass=f=300,lowpass=f=300"    # sisakan musik 110 Hz
        high = "highpass=f=700,highpass=f=700,highpass=f=700"  # sisakan narasi 1 kHz
        with tempfile.TemporaryDirectory() as tmp:
            narr, bgm, mix = (os.path.join(tmp, n) for n in ("narr.wav", "bgm.wav", "mix.wav"))
            # narasi: nada 1 kHz aktif 0-3 s, diam 3-7 s; musik: nada 110 Hz konstan 5 s (lebih pendek -> di-loop)
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=1000:d=7",
                            "-af", "volume=2,volume='if(lt(t,3),1,0)':eval=frame", narr],
                           check=True, stderr=subprocess.DEVNULL)
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=110:d=5", "-af", "volume=4", bgm],
                           check=True, stderr=subprocess.DEVNULL)
            subprocess.run(["ffmpeg", "-y", "-i", narr, "-stream_loop", "-1", "-i", bgm,
                            "-filter_complex", generator.build_audio_filter(0, 1), "-map", "[a]", "-t", "7", mix],
                           check=True, stderr=subprocess.DEVNULL)

            speaking = mean_db(mix, 1.0, 1.5, low)
            silent = mean_db(mix, 5.5, 1.0, low)
            print(f"musik saat bicara {speaking:.1f} dB, saat diam {silent:.1f} dB, turun {silent - speaking:.1f} dB")
            self.assertGreaterEqual(silent - speaking, 8.0)

            narr_in = mean_db(narr, 1.0, 1.5, high)
            narr_out = mean_db(mix, 1.0, 1.5, high)
            print(f"narasi masuk {narr_in:.1f} dB, keluar {narr_out:.1f} dB")
            self.assertAlmostEqual(narr_out, narr_in, delta=1.5)  # tidak lagi dibagi dua oleh amix

            # durasi 7 s tercapai walau musik hanya 5 s (di-loop)
            self.assertGreater(mean_db(mix, 6.0, 1.0, low), -40)


if __name__ == "__main__":
    unittest.main()
