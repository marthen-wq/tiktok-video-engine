#!/usr/bin/env python3
"""Penjadwal pipeline v3 (cron 15 menit di GitHub Actions).

  python scheduler.py tick          tombol Telegram, auto-approve, posting yang jatuh tempo, cari baris READY
  python scheduler.py render <row>  render satu baris lalu kirim preview ke Telegram

Status kolom F: READY -> RENDERING -> PREVIEW -> APPROVED -> POSTED (atau REJECTED / FAILED / MANUAL)
"""
import datetime as dt
import html
import json
import os
import sys
import traceback
from zoneinfo import ZoneInfo

import generator as g
import publish as p

AUDIENCE_TZ = ZoneInfo(os.environ.get("AUDIENCE_TZ") or "America/New_York")
LOCAL_TZ = ZoneInfo("Asia/Jakarta")
POST_SLOTS = sorted(s.strip() for s in (os.environ.get("POST_SLOTS") or "15:00,20:00").split(",") if s.strip())
APPROVAL_MODE = (os.environ.get("APPROVAL_MODE") or "manual").lower()   # manual | auto
MIN_LEAD = dt.timedelta(minutes=10)
STATE_TAB = "state"
DAYS = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
RUN_URL = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}"
           f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}")

# ---------------------------------------------------------------- Waktu & slot


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def to_iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def next_slot(now: dt.datetime, taken) -> dt.datetime:
    """Slot posting berikutnya (jam audiens, sadar DST) minimal 10 menit lagi dan belum dipakai baris lain."""
    local = now.astimezone(AUDIENCE_TZ)
    for day in range(14):
        d = (local + dt.timedelta(days=day)).date()
        for hhmm in POST_SLOTS:
            h, m = map(int, hhmm.split(":"))
            cand = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=AUDIENCE_TZ)
            if cand >= now + MIN_LEAD and to_iso(cand) not in taken:
                return cand
    raise RuntimeError("Tidak ada slot kosong dalam 14 hari")


def fmt_slot(t: dt.datetime) -> str:
    w, a = t.astimezone(LOCAL_TZ), t.astimezone(AUDIENCE_TZ)
    return f"{DAYS[w.weekday()]} {w.day} {MONTHS[w.month - 1]} {w:%H:%M} WIB ({a:%H:%M} {a.tzname()})"


def taken_slots(rows):
    return {r["scheduled_at"] for r in rows if r["status"].upper() == "APPROVED" and r["scheduled_at"]}

# ---------------------------------------------------------------- State (tab 'state': kunci | nilai)


def load_state(svc) -> dict:
    try:
        res = svc.spreadsheets().values().get(spreadsheetId=g.SPREADSHEET_ID, range=f"{STATE_TAB}!A1:B50").execute()
    except Exception:
        svc.spreadsheets().batchUpdate(spreadsheetId=g.SPREADSHEET_ID, body={
            "requests": [{"addSheet": {"properties": {"title": STATE_TAB}}}]}).execute()
        print(f"[+] Tab '{STATE_TAB}' dibuat")
        return {}
    return {r[0]: (r[1] if len(r) > 1 else "") for r in res.get("values", []) if r}


def save_state(svc, state: dict):
    values = [[k, str(v)] for k, v in sorted(state.items())]
    svc.spreadsheets().values().update(spreadsheetId=g.SPREADSHEET_ID, range=f"{STATE_TAB}!A1:B{len(values)}",
                                       valueInputOption="RAW", body={"values": values}).execute()

# ---------------------------------------------------------------- Aksi status


def approve(svc, row: dict, rows, now):
    slot = next_slot(now, taken_slots(rows))
    g.update_row(svc, row["row"], status="APPROVED", scheduled_at=to_iso(slot), error="")
    row["status"], row["scheduled_at"] = "APPROVED", to_iso(slot)
    p.tg_message(f"✅ Baris {row['row']} dijadwalkan: <b>{fmt_slot(slot)}</b>")
    print(f"[+] Baris {row['row']} disetujui, slot {to_iso(slot)}")


def handle_callbacks(svc, rows, state: dict, now) -> bool:
    """Proses tombol Telegram sejak offset terakhir. True bila state berubah."""
    updates = p.tg_updates(int(state.get("telegram_offset") or 0))
    by_row = {r["row"]: r for r in rows}
    for u in updates:
        state["telegram_offset"] = u["update_id"] + 1
        cq = u.get("callback_query")
        if not cq:
            continue
        msg = cq.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        if str(chat) != str(p.TELEGRAM_CHAT_ID):
            p.tg_answer(cq["id"], "Tidak diizinkan")
            continue
        action, _, num = (cq.get("data") or "").partition(":")
        row = by_row.get(int(num)) if num.isdigit() else None
        if not row:
            p.tg_answer(cq["id"], "Baris tidak ditemukan")
            continue
        status = row["status"].upper()
        if action == "ok" and status in ("PREVIEW", "FAILED"):
            approve(svc, row, rows, now)
            p.tg_answer(cq["id"], "Dijadwalkan")
        elif action == "redo" and status in ("PREVIEW", "FAILED", "APPROVED"):
            g.update_row(svc, row["row"], status="READY", scheduled_at="", error="")
            row["status"] = "READY"
            p.tg_answer(cq["id"], "Akan dirender ulang dalam ~15 menit")
        elif action == "no" and status in ("PREVIEW", "FAILED", "APPROVED"):
            g.update_row(svc, row["row"], status="REJECTED", scheduled_at="")
            row["status"] = "REJECTED"
            p.tg_answer(cq["id"], "Dibatalkan")
        else:
            p.tg_answer(cq["id"], f"Status baris sekarang {status}")
            continue
        p.tg_clear_buttons(chat, msg.get("message_id"))
    return bool(updates)


def youtube_text(meta: dict):
    credits = meta.get("credits") or {}
    lines = [meta.get("caption", ""), "", meta.get("hashtags", "")]
    if credits.get("music"):
        lines += ["", f"Music: {credits['music']}"]
    if credits.get("footage"):
        lines += [f"Footage: {', '.join(credits['footage'])}"]
    title = meta.get("yt_title") or (meta.get("caption", "")[:85] + " #shorts")
    tags = [t.lstrip("#") for t in meta.get("hashtags", "").split() if t.startswith("#")]
    return title, "\n".join(lines).strip(), tags


def tiktok_title(meta: dict) -> str:
    music = (meta.get("credits") or {}).get("music") or ""
    credit = " 🎵 Kevin MacLeod (CC BY)" if "Kevin MacLeod" in music else ""
    return f"{meta.get('caption', '')} {meta.get('hashtags', '')}{credit}".strip()


def post_row(svc, row: dict, state: dict):
    n = row["row"]
    work = os.path.join(g.TEMP_DIR, f"post-{n}")
    if not p.download_artifact(f"video-row-{n}", work):
        g.update_row(svc, n, status="FAILED", error="Artifact video tidak ditemukan (kedaluwarsa?)")
        p.tg_message(f"⚠️ Video baris {n} tidak ditemukan untuk diposting. Render ulang?",
                     [[{"text": "🔁 Render ulang", "callback_data": f"redo:{n}"}]])
        return
    with open(os.path.join(work, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    video = os.path.join(work, "video.mp4")
    ready = p.configured(state.get("tiktok_refresh_token") or os.environ.get("TIKTOK_REFRESH_TOKEN", ""))
    if not any(ready.values()):
        g.update_row(svc, n, status="MANUAL")
        p.tg_message(f"📲 Baris {n} sudah waktunya tayang, tapi belum ada platform yang terhubung. "
                     f"Unggah manual dari video preview di atas.\n\n{html.escape(tiktok_title(meta))}")
        return
    fields, errors, lines = {}, [], []
    if ready["tiktok"] and not row["tiktok_id"]:
        try:
            refresh = state.get("tiktok_refresh_token") or os.environ.get("TIKTOK_REFRESH_TOKEN", "")
            access, state["tiktok_refresh_token"] = p.tiktok_access_token(refresh)
            fields["tiktok_id"] = p.tiktok_upload(video, access, tiktok_title(meta))
            lines.append("• TikTok: " + ("terbit ✅" if p.TIKTOK_MODE == "direct" else
                                         "draft masuk inbox — buka notifikasi TikTok, tempel caption di bawah, lalu Post"))
        except Exception as e:
            errors.append(f"TikTok: {e}")
    if ready["youtube"] and not row["youtube_id"]:
        try:
            title, desc, tags = youtube_text(meta)
            fields["youtube_id"] = vid = p.youtube_upload(video, title, desc, tags)
            lines.append(f"• YouTube: https://youtube.com/shorts/{vid}")
        except Exception as e:
            errors.append(f"YouTube: {e}")
    status = "FAILED" if errors else "POSTED"
    g.update_row(svc, n, status=status, error="; ".join(errors)[:500], **fields)
    if errors:
        p.tg_message(f"⚠️ Posting baris {n} gagal:\n{html.escape(chr(10).join(errors))}",
                     [[{"text": "🔁 Coba posting lagi", "callback_data": f"ok:{n}"}]])
    else:
        p.tg_message(f"🚀 Baris {n} terposting:\n" + "\n".join(lines) +
                     f"\n\n<b>Caption:</b>\n{html.escape(tiktok_title(meta))}")
    print(f"[{'!' if errors else '+'}] Posting baris {n}: {status} {fields} {errors}")

# ---------------------------------------------------------------- Perintah


def write_output(key: str, value):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"[*] {key}={value}")


def tick():
    svc = g.get_sheets_service()
    rows, header = g.read_rows(svc)
    g.ensure_header(svc, header)
    state = load_state(svc)
    now = now_utc()
    changed = handle_callbacks(svc, rows, state, now)
    if APPROVAL_MODE == "auto":
        for r in rows:
            if r["status"].upper() == "PREVIEW":
                approve(svc, r, rows, now)
    due = [r for r in rows if r["status"].upper() == "APPROVED" and r["scheduled_at"]
           and from_iso(r["scheduled_at"]) <= now]
    if due:
        before = state.get("tiktok_refresh_token")
        post_row(svc, due[0], state)
        changed = changed or state.get("tiktok_refresh_token") != before
    if changed:
        save_state(svc, state)
    forced = (os.environ.get("FORCE_ROW") or "").strip()
    ready = [r for r in rows if r["status"].upper() == "READY"]
    write_output("render_row", forced or (ready[0]["row"] if ready else ""))


def preview_caption(row: dict, meta: dict, slot: dt.datetime) -> str:
    style = "Dark Stoic" if meta["style"] == "dark_stoic" else "Soft Healing"
    tts = {"gemini": "Gemini TTS", "edge-tts": "edge-tts (cadangan)"}.get(meta["tts"], meta["tts"])
    return (f"🎬 <b>Preview baris {row['row']}</b> · {style} · {meta['duration']:.0f} dtk · {tts}\n\n"
            f"<b>Caption:</b>\n{html.escape(meta['caption'])}\n{html.escape(meta['hashtags'])}\n\n"
            f"<b>Judul Shorts:</b> {html.escape(meta['yt_title'])}\n"
            f"<b>Jadwal bila disetujui:</b> {fmt_slot(slot)}\n"
            f"<a href=\"{RUN_URL}\">Log render</a>")


def render(row_num: int):
    svc = g.get_sheets_service()
    rows, _ = g.read_rows(svc)
    row = next((r for r in rows if r["row"] == row_num), None)
    if not row:
        sys.exit(f"Baris {row_num} tidak ada")
    g.update_row(svc, row_num, status="RENDERING", video_url=RUN_URL, error="")
    out_dir = os.path.join(g.OUTPUT_DIR, f"video-row-{row_num}")
    try:
        meta = g.render_job(g.parse_job(row), out_dir)
    except Exception as e:
        traceback.print_exc()
        g.update_row(svc, row_num, status="FAILED", error=f"render: {e}"[:500])
        p.tg_message(f"⚠️ Render baris {row_num} gagal: {html.escape(str(e)[:300])}\n<a href=\"{RUN_URL}\">Log</a>",
                     [[{"text": "🔁 Coba render lagi", "callback_data": f"redo:{row_num}"}]])
        sys.exit(1)
    g.update_row(svc, row_num, status="PREVIEW")
    row["status"] = "PREVIEW"
    slot = next_slot(now_utc(), taken_slots(rows))
    if p.TELEGRAM_BOT_TOKEN:
        p.tg_video(os.path.join(out_dir, "preview.mp4"), preview_caption(row, meta, slot),
                   p.approval_buttons(row_num))
    if APPROVAL_MODE == "auto":
        approve(svc, row, rows, now_utc())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if cmd == "tick":
        tick()
    elif cmd == "render":
        render(int(sys.argv[2]))
    else:
        sys.exit(__doc__)
