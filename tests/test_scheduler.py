"""Tes offline untuk slot posting dan tombol Telegram (tanpa jaringan).

Jalankan dari root repo:  python3 -m unittest discover -s tests -v
"""
import datetime as dt
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scheduler  # noqa: E402

UTC = dt.timezone.utc


class NextSlotTest(unittest.TestCase):
    def test_summer_slot_is_15_et_which_is_02_wib(self):
        now = dt.datetime(2026, 10, 10, 3, 0, tzinfo=UTC)            # 10:00 WIB, 23:00 ET kemarin
        slot = scheduler.next_slot(now, set())
        self.assertEqual(scheduler.to_iso(slot), "2026-10-10T19:00:00Z")
        self.assertEqual(scheduler.fmt_slot(slot), "Min 11 Okt 02:00 WIB (15:00 EDT)")

    def test_winter_slot_shifts_with_dst(self):
        now = dt.datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
        slot = scheduler.next_slot(now, set())
        self.assertEqual(scheduler.to_iso(slot), "2026-11-10T20:00:00Z")   # 15:00 EST = 03:00 WIB

    def test_taken_and_too_close_slots_are_skipped(self):
        now = dt.datetime(2026, 10, 10, 18, 55, tzinfo=UTC)          # 5 menit sebelum 15:00 ET
        slot = scheduler.next_slot(now, {"2026-10-11T00:00:00Z"})    # 20:00 ET sudah dipakai
        self.assertEqual(scheduler.to_iso(slot), "2026-10-11T19:00:00Z")


class CallbackTest(unittest.TestCase):
    def setUp(self):
        self.update_row = mock.patch.object(scheduler.g, "update_row").start()
        self.answers = []
        mock.patch.object(scheduler.p, "tg_answer", side_effect=lambda cid, t: self.answers.append(t)).start()
        mock.patch.object(scheduler.p, "tg_clear_buttons").start()
        mock.patch.object(scheduler.p, "tg_message").start()
        mock.patch.object(scheduler.p, "TELEGRAM_CHAT_ID", "42").start()
        self.rows = [{"row": 7, "status": "PREVIEW", "scheduled_at": ""},
                     {"row": 8, "status": "APPROVED", "scheduled_at": "2026-10-10T19:00:00Z"}]
        self.now = dt.datetime(2026, 10, 10, 3, 0, tzinfo=UTC)

    def tearDown(self):
        mock.patch.stopall()

    def _press(self, data, chat=42, update_id=100):
        upd = [{"update_id": update_id, "callback_query": {"id": "c", "data": data,
                                                           "message": {"chat": {"id": chat}, "message_id": 5}}}]
        mock.patch.object(scheduler.p, "tg_updates", return_value=upd).start()
        state = {}
        scheduler.handle_callbacks(None, self.rows, state, self.now)
        return state

    def test_approve_takes_next_free_slot(self):
        state = self._press("ok:7")
        self.assertEqual(state["telegram_offset"], 101)
        self.assertEqual(self.rows[0]["status"], "APPROVED")
        self.assertEqual(self.rows[0]["scheduled_at"], "2026-10-11T00:00:00Z")  # 15:00 ET sudah milik baris 8

    def test_redo_sends_row_back_to_ready(self):
        self._press("redo:7")
        self.assertEqual(self.rows[0]["status"], "READY")
        self.update_row.assert_called_with(None, 7, status="READY", scheduled_at="", error="")

    def test_other_chat_cannot_press_buttons(self):
        self._press("ok:7", chat=999)
        self.assertEqual(self.rows[0]["status"], "PREVIEW")
        self.assertEqual(self.answers, ["Tidak diizinkan"])
        self.update_row.assert_not_called()

    def test_stale_button_does_nothing(self):
        self.rows[0]["status"] = "POSTED"
        self._press("ok:7")
        self.update_row.assert_not_called()
        self.assertIn("POSTED", self.answers[0])


class TextTest(unittest.TestCase):
    def test_youtube_text_includes_credits_and_tags(self):
        meta = {"caption": "You are not behind.", "hashtags": "#stoic #mindset", "yt_title": "",
                "credits": {"music": '"Inspired" by Kevin MacLeod', "footage": ["Ann (Pexels)"]}}
        title, desc, tags = scheduler.youtube_text(meta)
        self.assertTrue(title.endswith("#shorts"))
        self.assertIn("Music: \"Inspired\" by Kevin MacLeod", desc)
        self.assertIn("Footage: Ann (Pexels)", desc)
        self.assertEqual(tags, ["stoic", "mindset"])
        self.assertIn("Kevin MacLeod (CC BY)", scheduler.tiktok_title(meta))


if __name__ == "__main__":
    unittest.main()
