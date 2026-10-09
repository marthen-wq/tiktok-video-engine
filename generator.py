#!/usr/bin/env python3
"""
TikTok Shorts Video Engine v3
- Job dari Google Sheets: naskah per adegan (markup [pause], [long pause], *penekanan*), visual, mood, gaya
- Narasi ekspresif Gemini TTS (cadangan edge-tts) + waktu per kata via faster-whisper
- Footage per adegan dari Pexels/Pixabay dengan grading per gaya
- Teks kinetik ASS: Dark Stoic (kata menyala saat diucapkan) / Soft Healing (frasa lembut)
- Musik CC BY per mood dengan ducking

Jalankan manual:  python generator.py <baris>   atau   QUOTE_INPUT="..." python generator.py
"""

import asyncio
import difflib
import json
import os
import random
import re
import subprocess
import sys
import time
import requests

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1wQepTnnoZi0rO5oPKkP5Qq8dfIcwqiAPg1r9_tadLf4")
GCP_SA_KEY = os.environ.get("GCP_SERVICE_ACCOUNT_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")

OUTPUT_DIR = "output"
TEMP_DIR = "temp"
ASSETS_DIR = "assets"
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

# ---------------------------------------------------------------- Google Sheets

SHEET = "Sheet1"
COLUMNS = ["script", "visuals", "music_mood", "style", "video_url", "status", "voice_direction",
           "caption", "hashtags", "yt_title", "trend_ref", "scheduled_at", "tiktok_id", "youtube_id", "error"]


def col_letter(name: str) -> str:
    return chr(ord("A") + COLUMNS.index(name))


def get_sheets_service():
    if not GCP_SA_KEY:
        print("[!] GCP_SERVICE_ACCOUNT_KEY tidak ditemukan!")
        return None
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(GCP_SA_KEY)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_rows(service):
    """Semua baris data Sheet1 sebagai dict per kolom (+ 'row' = nomor baris), dan header saat ini."""
    res = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET}!A1:{col_letter(COLUMNS[-1])}1000").execute()
    values = res.get("values", [])
    rows = []
    for idx, r in enumerate(values[1:], start=2):
        r = list(r) + [""] * (len(COLUMNS) - len(r))
        row = {k: (v or "").strip() for k, v in zip(COLUMNS, r)}
        row["row"] = idx
        rows.append(row)
    return rows, (values[0] if values else [])


def ensure_header(service, header):
    if [h.strip().lower() for h in header[:len(COLUMNS)]] != COLUMNS:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{SHEET}!A1:{col_letter(COLUMNS[-1])}1",
            valueInputOption="RAW", body={"values": [COLUMNS]}).execute()
        print("[+] Header Sheet1 diperbarui ke format v3")


def update_row(service, row: int, **fields):
    data = [{"range": f"{SHEET}!{col_letter(k)}{row}", "values": [[str(v)]]} for k, v in fields.items()]
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID, body={"valueInputOption": "RAW", "data": data}).execute()

# ---------------------------------------------------------------- Job & naskah

STYLES = {
    "dark_stoic": {
        "voice": "Algenib",
        "edge_voice": "en-US-ChristopherNeural",
        "tts_style": "low, weary and intense at a measured, natural pace, building to quiet unshakable resolve",
        "grade": "hue=s=0,eq=contrast=1.35:brightness=-0.05,vignette=PI/4",
        "transitions": ["fade", "fadeblack"],
        "xfade": 0.6,
        "fallback_color": "0x0b0b0b",
        "default_visual": "dark storm clouds",
        "default_mood": "dark_reflective",
    },
    "soft_healing": {
        "voice": "Sulafat",
        "edge_voice": "en-US-AvaNeural",
        "tts_style": "warm, gentle and intimate, like comforting a close friend late at night",
        "grade": "eq=contrast=0.95:saturation=1.1:brightness=0.02,"
                 "colorbalance=rs=0.08:bs=-0.08:rm=0.05:bm=-0.05,vignette=PI/5",
        "transitions": ["dissolve", "fade"],
        "xfade": 0.8,
        "fallback_color": "0x2b1d16",
        "default_visual": "calm ocean waves at sunset",
        "default_mood": "soft_hopeful",
    },
}
DEFAULT_STYLE = "dark_stoic"
PAUSE_TAG = re.compile(r"\[(long pause|pause)\]", re.I)


def parse_script(script: str):
    """Naskah bermarkup -> daftar adegan; tiap adegan daftar kata {text, emph, pause, scene}.

    Adegan dipisah baris kosong. [pause]/[long pause] menempel ke kata sebelumnya,
    *kata* (boleh beberapa kata) menandai penekanan.
    """
    scenes = []
    for para in re.split(r"\n\s*\n", script.strip()):
        words, open_emph = [], False
        for tok in re.findall(r"\[[^\]]*\]|[^\s\[]+", para):
            tag = PAUSE_TAG.fullmatch(tok)
            if tag:
                if words:
                    words[-1]["pause"] = "long" if tag.group(1).lower() == "long pause" else "short"
                continue
            if tok.startswith("["):
                continue  # tag lain diabaikan
            stars = tok.count("*")
            text = tok.replace("*", "")
            emph = open_emph or stars > 0
            if stars % 2:
                open_emph = not open_emph
            if text:
                words.append({"text": text, "emph": emph, "pause": None, "scene": len(scenes)})
        if words:
            scenes.append(words)
    return scenes


def tts_text(scenes, flavor: str) -> str:
    """Teks untuk TTS. 'gemini': tag jeda Gemini + kata ditekankan KAPITAL. 'plain': jeda jadi tanda baca."""
    out = []
    for scene in scenes:
        parts = []
        for w in scene:
            t = w["text"].upper() if flavor == "gemini" and w["emph"] else w["text"]
            if w["pause"] and flavor == "gemini":
                t += " <long pause>" if w["pause"] == "long" else " <short pause>"
            elif w["pause"]:
                t += "..." if w["pause"] == "long" else ("" if t[-1] in ",.;:!?" else ",")
            parts.append(t)
        out.append(" ".join(parts))
    return "\n\n".join(out)


def parse_job(row: dict) -> dict:
    style = (row.get("style") or "").strip().lower()
    if style not in STYLES:
        style = DEFAULT_STYLE
    cfg = STYLES[style]
    scenes = parse_script(row.get("script", ""))
    if not scenes:
        raise ValueError("Kolom script kosong")
    visuals = [v.strip() for v in re.split(r"\n| \| ", row.get("visuals", "")) if v.strip()]
    if len(visuals) != len(scenes):
        print(f"[!] {len(visuals)} baris visual untuk {len(scenes)} adegan, disesuaikan otomatis")
    visuals = (visuals or [cfg["default_visual"]])[:len(scenes)]
    visuals += [visuals[-1]] * (len(scenes) - len(visuals))
    mood = (row.get("music_mood") or "").strip().lower()
    return {
        "row": row.get("row"),
        "style": style,
        "cfg": cfg,
        "scenes": scenes,
        "visuals": visuals,
        "mood": mood if mood in MUSIC else cfg["default_mood"],
        "direction": row.get("voice_direction", ""),
        "caption": row.get("caption", ""),
        "hashtags": row.get("hashtags", ""),
        "yt_title": row.get("yt_title", ""),
    }

# ---------------------------------------------------------------- Narasi

TICKS_PER_SEC = 10_000_000  # edge-tts melaporkan offset/durasi dalam satuan 100 ns
GEMINI_ATTEMPTS = 3          # tier gratis: 3 request/menit, jadi 429 ditunggu lalu dicoba lagi


def gemini_tts(text: str, voice: str, style_note: str, out_wav: str) -> bool:
    if not GEMINI_API_KEY:
        print("[!] GEMINI_API_KEY tidak ada, narasi memakai edge-tts")
        return False
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(GEMINI_ATTEMPTS):
        try:
            resp = client.models.generate_content(
                model=GEMINI_TTS_MODEL,
                contents=[{"role": "user", "parts": [{"text": text, "speech_metadata": {"style": style_note}}]}],
                config={"response_modalities": ["AUDIO"], "speech_config": {"voice_config": {"voice": voice}}},
            )
            with open(out_wav, "wb") as f:
                f.write(resp.candidates[0].content.parts[0].inline_data.data)
            print(f"[+] Narasi Gemini TTS ({voice}) selesai")
            return True
        except Exception as e:
            msg = str(e)
            if "429" in msg and attempt < GEMINI_ATTEMPTS - 1:
                m = re.search(r"retryDelay'?: '?(\d+)", msg)
                wait = min(int(m.group(1)) + 2 if m else 30, 65)
                print(f"[!] Kuota Gemini per menit habis, tunggu {wait}s")
                time.sleep(wait)
                continue
            print(f"[!] Gemini TTS gagal: {msg[:200]}")
            return False
    return False


async def generate_narration(text: str, output_path: str, voice: str = "en-US-ChristopherNeural",
                             rate: str = "-8%", pitch: str = "-2Hz"):
    """Narasi cadangan edge-tts; kembalikan event batas kata/kalimat (detik) untuk sinkronisasi."""
    import edge_tts
    print(f"[*] Menghasilkan audio TTS cadangan (edge-tts {voice})...")
    kwargs = dict(text=text, voice=voice, rate=rate, pitch=pitch)
    try:
        communicate = edge_tts.Communicate(boundary="WordBoundary", **kwargs)
    except TypeError:  # edge-tts lama tanpa parameter boundary
        communicate = edge_tts.Communicate(**kwargs)

    events = []
    with open(output_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                start = chunk["offset"] / TICKS_PER_SEC
                events.append({
                    "kind": chunk["type"],
                    "text": chunk["text"],
                    "start": start,
                    "end": start + chunk["duration"] / TICKS_PER_SEC,
                })
    return events

PAUSE_WEIGHT = {",": 2, ";": 2, ":": 2, ".": 4, "!": 4, "?": 4}  # jeda setelah tanda baca (setara karakter)


def spread_words(words, t0: float, t1: float):
    """Bagi rentang [t0, t1] ke kata-kata sebanding panjangnya (+ jeda setelah tanda baca)."""
    if not words:
        return []
    weights = [max(1, len(w.strip(",.;:!?\"'"))) + PAUSE_WEIGHT.get(w[-1], 0) for w in words]
    total, span = float(sum(weights)), max(t1 - t0, 0.0)
    out, cur = [], t0
    for w, wt in zip(words, weights):
        nxt = cur + span * wt / total
        out.append((w, cur, nxt))
        cur = nxt
    return out


def build_word_timings(text: str, events, duration: float):
    """Hasilkan [(kata, mulai, selesai)] dari event edge-tts.

    1. Event WordBoundary dari TTS (waktu ucapan sebenarnya).
    2. Event SentenceBoundary: kata dibagi proporsional di dalam tiap kalimat.
    3. Tanpa event: seluruh durasi audio dibagi proporsional panjang kata.
    """
    words = text.split()
    if not words:
        return []
    word_ev = [e for e in events if e["kind"] == "WordBoundary" and e["text"].strip()]
    if word_ev:
        print(f"[*] Sinkronisasi subtitle: WordBoundary ({len(word_ev)} kata)")
        if len(word_ev) == len(words):  # pertahankan tanda baca dari teks asli
            return [(w, e["start"], e["end"]) for w, e in zip(words, word_ev)]
        return [(e["text"].strip(), e["start"], e["end"]) for e in word_ev]
    sent_ev = [e for e in events if e["kind"] == "SentenceBoundary" and e["text"].strip()]
    if sent_ev and sum(len(e["text"].split()) for e in sent_ev) == len(words):
        print(f"[*] Sinkronisasi subtitle: SentenceBoundary ({len(sent_ev)} kalimat)")
        out, i = [], 0
        for e in sent_ev:
            n = len(e["text"].split())
            out += spread_words(words[i:i + n], e["start"], e["end"])
            i += n
        return out
    print("[!] Tidak ada event batas dari TTS, subtitle dibagi proporsional panjang kata")
    return spread_words(words, 0.0, duration)


def transcribe_words(wav: str):
    """[(kata, mulai, selesai)] dari faster-whisper (Gemini TTS tidak memberi waktu per kata)."""
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(wav, language="en", word_timestamps=True)
    return [(w.word.strip(), w.start, w.end) for s in segments for w in (s.words or [])]


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", word.lower())


def align_words(script_words, asr, duration: float):
    """Pasangkan kata naskah dengan kata hasil ASR; kata yang tak cocok diisi interpolasi."""
    times = [None] * len(script_words)
    sm = difflib.SequenceMatcher(a=[_norm(w) for w in script_words], b=[_norm(w) for w, _, _ in asr],
                                 autojunk=False)
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            times[i + k] = (asr[j + k][1], asr[j + k][2])
    i = 0
    while i < len(times):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(times) and times[j] is None:
            j += 1
        t0 = times[i - 1][1] if i > 0 else 0.0
        t1 = times[j][0] if j < len(times) else duration
        for k, (_, s, e) in enumerate(spread_words(script_words[i:j], t0, max(t0, t1))):
            times[i + k] = (s, e)
        i = j
    return times


def probe_duration(path: str) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stderr=subprocess.DEVNULL).decode().strip()
        return float(out)
    except Exception:
        return 0.0


MAX_PAUSE = 1.2  # detik; Gemini memberi jeda 2-4 s untuk tag jeda (hening 42% di smoke run, referensi 21-25%)


def silences(wav: str):
    """[(mulai, selesai)] hening >= 0,25 s pada -35 dB; metode yang sama dengan analisis video referensi."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", wav, "-af",
                          "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    return list(zip(starts, ends))


def cap_pauses(wav: str, max_pause: float = MAX_PAUSE) -> float:
    """Potong bagian tengah setiap hening yang lebih panjang dari max_pause. Kembalikan detik yang dibuang."""
    cuts = [(s + max_pause / 2, e - max_pause / 2) for s, e in silences(wav) if e - s > max_pause]
    if not cuts:
        return 0.0
    keep, prev = [], 0.0
    for a, b in cuts:
        keep.append((prev, a))
        prev = b
    graph = "".join(f"[0:a]atrim=start={a:.3f}" + (f":end={b:.3f}" if b is not None else "")
                    + f",asetpts=PTS-STARTPTS[k{i}];" for i, (a, b) in enumerate(keep + [(prev, None)]))
    graph += "".join(f"[k{i}]" for i in range(len(keep) + 1)) + f"concat=n={len(keep) + 1}:v=0:a=1[out]"
    tmp = wav + ".cap.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-filter_complex", graph, "-map", "[out]", tmp],
                   check=True)
    os.replace(tmp, wav)
    return sum(b - a for a, b in cuts)


def make_narration(job: dict, audio_path: str):
    """Rekam narasi lalu isi start/end di setiap kata. Kembalikan (durasi, sumber)."""
    words = [w for scene in job["scenes"] for w in scene]
    texts = [w["text"] for w in words]
    cfg = job["cfg"]
    style_note = cfg["tts_style"] + (f". {job['direction']}" if job["direction"] else "")
    if gemini_tts(tts_text(job["scenes"], "gemini"), cfg["voice"], style_note, audio_path):
        removed = cap_pauses(audio_path)
        if removed:
            print(f"[*] Jeda panjang dipangkas ke maks {MAX_PAUSE}s ({removed:.1f}s hening dibuang)")
        duration = probe_duration(audio_path)
        try:
            asr = transcribe_words(audio_path)
            print(f"[*] Sinkronisasi kata: faster-whisper ({len(asr)} kata terdengar, {len(words)} di naskah)")
        except Exception as e:
            print(f"[!] faster-whisper gagal ({e}), waktu kata dibagi proporsional")
            asr = []
        times, source = align_words(texts, asr, duration), "gemini"
    else:
        events = asyncio.run(generate_narration(tts_text(job["scenes"], "plain"), audio_path,
                                                voice=cfg["edge_voice"]))
        duration = probe_duration(audio_path)
        timed = build_word_timings(" ".join(texts), events, duration)
        if len(timed) != len(texts):
            timed = spread_words(texts, 0.0, duration)
        times, source = [(s, e) for _, s, e in timed], "edge-tts"
    for w, (s, e) in zip(words, times):
        w["start"], w["end"] = s, e
    silent = sum(e - s for s, e in silences(audio_path))
    speaking = max(duration - silent, 0.1)
    print(f"[*] Tempo narasi ({source}): {len(words) / speaking * 60:.0f} wpm saat bicara, "
          f"hening {silent / max(duration, 0.1) * 100:.0f}%, durasi {duration:.1f}s "
          f"(target referensi 158-181 wpm, hening 21-25%)")
    return duration, source

# ---------------------------------------------------------------- Footage per adegan

SHOT_SECONDS = 6.5          # target lama satu shot (referensi: 5,5-7 detik)
MAX_SLOWDOWN = 1.6          # klip lebih pendek dari shot diperlambat sampai faktor ini, sisanya di-loop
USER_AGENT = "TikTokShortsVideoEngine/3.0 (+https://github.com/marthen-wq/tiktok-video-engine) python-requests"
DOWNLOAD_ATTEMPTS = 3
MAX_RETRY_WAIT = 20  # detik
_failed_urls = set()  # URL yang sudah gagal di run ini tidak dicoba lagi


def _retry_wait(resp, attempt: int) -> float:
    try:
        return min(MAX_RETRY_WAIT, float(resp.headers.get("Retry-After", "")))
    except ValueError:
        return min(MAX_RETRY_WAIT, 2.0 * 2 ** attempt)


def _download_one(url: str, dest: str) -> str:
    """Hasil: 'ok', 'missing' (coba kandidat lain), atau 'limited' (berhenti)."""
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, stream=True)
        except Exception as e:
            print(f"[!] Gagal mengunduh {url} ({e})")
            return "missing"
        if r.status_code in (429, 503):
            r.close()
            if attempt == DOWNLOAD_ATTEMPTS - 1:
                print(f"[!] {r.status_code} terus-menerus dari {url.split('/')[2]}, berhenti mencoba")
                return "limited"
            wait = _retry_wait(r, attempt)
            print(f"[!] {r.status_code} dari {url.split('/')[2]}, coba lagi dalam {wait:.0f}s")
            time.sleep(wait)
            continue
        if r.status_code != 200:
            r.close()
            return "missing"
        size = 0
        try:
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    size += len(chunk)
                    if size > 15 * 1024 * 1024:
                        break
        except Exception as e:
            print(f"[!] Unduhan terputus {url} ({e})")
            return "missing"
        ok = probe_duration(dest) > 0
        print(f"[{'+' if ok else '!'}] Klip {url.rsplit('/', 1)[-1][:60]}: {size // 1024} KB, {'valid' if ok else 'tidak terbaca'}")
        return "ok" if ok else "missing"
    return "limited"


def download_clip(url: str, dest: str) -> bool:
    """Unduh footage (maks ~15MB). True jika hasilnya video yang terbaca ffprobe."""
    if os.path.exists(dest) and probe_duration(dest) > 0:
        return True
    if url in _failed_urls:
        return False
    if _download_one(url, dest) == "ok":
        return True
    _failed_urls.add(url)
    return False


def remux_clip(raw: str, dest: str) -> bool:
    """Salin ulang stream video ke MKV agar durasi sesuai data yang benar-benar terunduh.

    Unduhan yang dipotong di ~15MB tetap membawa header durasi penuh, sehingga titik
    mulai acak bisa jatuh di luar data yang ada.
    """
    if os.path.exists(dest) and probe_duration(dest) > 0:
        return True
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-map", "0:v:0", "-c", "copy", dest])
    real = probe_duration(dest)
    print(f"[*] Durasi footage terpakai: {real:.1f}s (header: {probe_duration(raw):.1f}s)")
    return real > 0


def search_footage(query: str):
    """Kandidat footage untuk satu adegan: video portrait Pexels, video Pixabay, lalu foto Pexels."""
    out = []
    headers = {"Authorization": PEXELS_API_KEY}
    if PEXELS_API_KEY:
        try:
            r = requests.get("https://api.pexels.com/videos/search", headers=headers, timeout=20,
                             params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 15})
            for v in r.json().get("videos", []):
                files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"
                         and (f.get("height") or 0) >= 1280 and (f.get("width") or 0) < (f.get("height") or 0)]
                if files:
                    best = min(files, key=lambda f: abs(f["height"] - 1920))
                    out.append({"id": f"pexels-v{v['id']}", "kind": "video", "url": best["link"],
                                "credit": f"{v['user']['name']} (Pexels)"})
        except Exception as e:
            print(f"[!] Pencarian video Pexels gagal: {e}")
    if PIXABAY_API_KEY:
        try:
            r = requests.get("https://pixabay.com/api/videos/", timeout=20,
                             params={"key": PIXABAY_API_KEY, "q": query[:100], "per_page": 10, "safesearch": "true"})
            for h in r.json().get("hits", []):
                v = h["videos"].get("large") or {}
                if not v.get("url") or (v.get("height") or 0) < 1080:
                    v = h["videos"].get("medium") or {}
                if v.get("url"):
                    out.append({"id": f"pixabay-v{h['id']}", "kind": "video", "url": v["url"],
                                "credit": f"{h.get('user', 'Pixabay')} (Pixabay)"})
        except Exception as e:
            print(f"[!] Pencarian video Pixabay gagal: {e}")
    if PEXELS_API_KEY:
        try:
            r = requests.get("https://api.pexels.com/v1/search", headers=headers, timeout=20,
                             params={"query": query, "orientation": "portrait", "per_page": 10})
            for p in r.json().get("photos", []):
                out.append({"id": f"pexels-p{p['id']}", "kind": "photo", "url": p["src"]["large2x"],
                            "credit": f"{p['photographer']} (Pexels)"})
        except Exception as e:
            print(f"[!] Pencarian foto Pexels gagal: {e}")
    print(f"[*] Footage '{query}': {sum(c['kind'] == 'video' for c in out)} video, "
          f"{sum(c['kind'] == 'photo' for c in out)} foto")
    return out


def push_in(zoom_in: bool, scale_first: str) -> str:
    """Gerak kamera pelan (push-in atau pull-out) dengan zoompan per frame."""
    z = "min(1+0.0007*on,1.12)" if zoom_in else "max(1.12-0.0007*on,1)"
    return (f"{scale_first},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s=1080x1920:fps=30")


def shot_filter(grade: str, zoom_in: bool, photo: bool = False, speed: float = 1.0) -> str:
    size = "2160:3840" if photo else "1080:1920"  # foto diperbesar dulu supaya zoom tidak bergetar
    base = f"scale={size}:force_original_aspect_ratio=increase,crop={size},setsar=1"
    pre = f"setpts={speed:.3f}*PTS," if speed > 1.0 else ""
    return f"{pre}{push_in(zoom_in, base)},{grade},format=yuv420p"


SEGMENT_TOLERANCE = 0.15  # toleransi pembulatan frame saat memeriksa panjang segmen (detik)


def encode_segment(clip: str, start, seg_len: float, out_path: str, vf: str):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-stream_loop", "-1", "-i", clip, "-t", f"{seg_len:.3f}", "-an",
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out_path]
    subprocess.run(cmd, check=True)


def make_segment(clip: str, seg_len: float, out_path: str, grade: str = "null", zoom_in: bool = True) -> bool:
    """Potong satu shot 9:16 dari titik acak. Klip yang kurang panjang diperlambat (maks 1,6x), lalu di-loop."""
    clip_len = probe_duration(clip)
    name = os.path.basename(out_path)
    if clip_len > seg_len + 0.5:
        tries = [(random.uniform(0, clip_len - seg_len - 0.25), 1.0), (None, 1.0)]
    else:
        speed = min(MAX_SLOWDOWN, seg_len / max(clip_len, 0.1) * 1.02)
        tries = [(None, speed)]
    for start, speed in tries:
        label = f"mulai {start:.1f}s" if start is not None else f"dari awal (x{speed:.2f} lebih lambat)"
        try:
            encode_segment(clip, start, seg_len, out_path, shot_filter(grade, zoom_in, speed=speed))
        except subprocess.CalledProcessError as e:
            print(f"[!] Segmen {name} gagal di-encode ({label}): {e}")
            continue
        got = probe_duration(out_path)
        if got >= seg_len - SEGMENT_TOLERANCE:
            print(f"[+] Segmen {name}: {label}, {got:.2f}s")
            return True
        print(f"[!] Segmen {name} terlalu pendek: {got:.2f}s dari {seg_len:.2f}s ({label})")
    return False


def make_photo_segment(url: str, seg_len: float, out_path: str, grade: str, zoom_in: bool) -> bool:
    img = out_path + ".jpg"
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        if r.status_code != 200 or len(r.content) < 10_000:
            return False
        with open(img, "wb") as f:
            f.write(r.content)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "30", "-i", img,
                        "-t", f"{seg_len:.3f}", "-vf", shot_filter(grade, zoom_in, photo=True),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out_path], check=True)
    except Exception as e:
        print(f"[!] Foto {url[-40:]} gagal: {e}")
        return False
    ok = probe_duration(out_path) >= seg_len - SEGMENT_TOLERANCE
    print(f"[{'+' if ok else '!'}] Segmen foto {os.path.basename(out_path)}: {probe_duration(out_path):.2f}s")
    return ok


def make_fallback_segment(seg_len: float, out_path: str, color: str = "0x0d1117"):
    """Segmen cadangan jika semua footage gagal, agar durasi tetap utuh."""
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c={color}:s=1080x1920:d={seg_len:.3f}:r=30",
        "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", out_path
    ], check=True)


def crossfade_segments(segments, lengths, xf: float, transitions, output_path: str):
    """Sambung segmen dengan xfade; segmen ke-k mulai di sum(panjang sebelumnya) - k*xf."""
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for seg in segments:
        cmd += ["-i", seg]
    if len(segments) > 1:
        parts, last, offset = [], "0:v", 0.0
        for i in range(1, len(segments)):
            offset += lengths[i - 1] - xf
            tr = transitions[(i - 1) % len(transitions)]
            parts.append(f"[{last}][{i}:v]xfade=transition={tr}:duration={xf:.3f}:offset={offset:.3f}[v{i}]")
            last = f"v{i}"
        cmd += ["-filter_complex", ";".join(parts), "-map", f"[{last}]"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", output_path]
    subprocess.run(cmd, check=True)


def extend_to_duration(path: str, total: float):
    """Pengaman terakhir: bila background lebih pendek dari narasi, tahan frame terakhir sampai `total`."""
    got = probe_duration(path)
    if got >= total - 0.3:
        return
    print(f"[!] Background hanya {got:.1f}s dari {total:.1f}s, frame terakhir diperpanjang")
    padded = path + ".pad.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", path,
        "-vf", f"tpad=stop_mode=clone:stop_duration={total - got + 0.1:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", padded
    ], check=True)
    os.replace(padded, path)


def plan_shots(spans, xf_max: float):
    """Pecah tiap adegan [mulai, selesai) jadi shot ~SHOT_SECONDS. Kembalikan (shot, xf).

    Shot non-terakhir diperpanjang xf agar total setelah crossfade tepat sama dengan total adegan.
    """
    shots = []
    for scene, (s, e) in enumerate(spans):
        n = max(1, round((e - s) / SHOT_SECONDS))
        shots += [{"scene": scene, "len": (e - s) / n} for _ in range(n)]
    xf = min(xf_max, min(sh["len"] for sh in shots) / 3)
    for sh in shots[:-1]:
        sh["len"] += xf
    return shots, xf


def prepare_scene_video(job: dict, spans, output_path: str):
    """Susun footage per adegan sesuai kata kunci visual; kembalikan daftar kredit."""
    cfg = job["cfg"]
    shots, xf = plan_shots(spans, cfg["xfade"])
    print(f"[*] Menyusun {len(shots)} shot untuk {len(spans)} adegan (crossfade {xf:.2f}s)...")
    used, credits, segments, cache = set(), [], [], {}
    for i, shot in enumerate(shots):
        query = job["visuals"][shot["scene"]]
        if query not in cache:
            cache[query] = search_footage(query)
        seg_path = os.path.join(TEMP_DIR, f"shot_{i}.mp4")
        zoom_in = i % 2 == 0
        ok = False
        for cand in [c for c in cache[query] if c["id"] not in used]:
            used.add(cand["id"])
            if cand["kind"] == "photo":
                ok = make_photo_segment(cand["url"], shot["len"], seg_path, cfg["grade"], zoom_in)
            else:
                raw = os.path.join(TEMP_DIR, f"raw_{cand['id']}.mp4")
                clip = os.path.join(TEMP_DIR, f"clip_{cand['id']}.mkv")
                ok = (download_clip(cand["url"], raw) and remux_clip(raw, clip)
                      and make_segment(clip, shot["len"], seg_path, cfg["grade"], zoom_in))
            if ok:
                credits.append(cand["credit"])
                break
        if not ok:
            print(f"[!] Shot {i + 1} ('{query}') memakai warna polos cadangan")
            make_fallback_segment(shot["len"], seg_path, cfg["fallback_color"])
        segments.append(seg_path)
    crossfade_segments(segments, [s["len"] for s in shots], xf, cfg["transitions"], output_path)
    extend_to_duration(output_path, spans[-1][1])
    print(f"[+] Background per adegan siap: {probe_duration(output_path):.1f}s")
    return sorted(set(credits))

# ---------------------------------------------------------------- Teks kinetik (ASS)

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
CAPTION_STYLES = {
    # kapital tebal kecil di tengah; kata abu-abu menyala putih tepat saat diucapkan (referensi "Get up")
    "dark_stoic": {
        "style": "Style: Default,Montserrat ExtraBold,60,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
                 "0,0,0,0,100,100,1,0,1,0,2,5,150,150,0,1",
        "max_words": 6, "hold": 0.5, "fade": (120, 150), "upper": True,
    },
    # serif tipis, frasa utuh muncul dan hilang lembut (referensi "Keep going")
    "soft_healing": {
        "style": "Style: Default,Lora,56,&H00FFFFFF,&H000000FF,&H00000000,&H50000000,"
                 "0,0,0,0,100,100,0,0,1,0,1.5,5,140,140,0,1",
        "max_words": 8, "hold": 0.8, "fade": (350, 400), "upper": False,
    },
}
UNSPOKEN = "&H707070&"   # warna kata yang belum diucapkan (BGR)
MAX_PHRASE_GAP = 0.7     # jeda ucapan lebih panjang dari ini memulai frasa baru
JOIN_GAP = 0.8           # frasa berikutnya yang mulai dalam rentang ini langsung menyambung


def group_phrases(words, max_words: int):
    phrases, cur = [], []
    for w in words:
        if cur:
            prev = cur[-1]
            if (w["scene"] != prev["scene"] or len(cur) >= max_words or prev["pause"]
                    or w["start"] - prev["end"] > MAX_PHRASE_GAP
                    or re.search(r"[.!?]$", prev["text"])
                    or (re.search(r"[,;:\u2014-]$", prev["text"]) and len(cur) >= 3)):
                phrases.append(cur)
                cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return phrases


def ass_time(s: float) -> str:
    cs = int(round(max(s, 0.0) * 100))
    return f"{cs // 360000:d}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def caption_text(phrase, start: float, style: str) -> str:
    cs = CAPTION_STYLES[style]
    head = "{\\fad(%d,%d)}" % cs["fade"]
    parts = []
    for w in phrase:
        t = _esc(w["text"].upper() if cs["upper"] else w["text"])
        if style == "dark_stoic":
            t0 = max(0, int((w["start"] - start) * 1000))
            size = "\\fscx125\\fscy125" if w["emph"] else ""
            reset = "{\\fscx100\\fscy100}" if w["emph"] else ""
            parts.append(f"{{\\1c{UNSPOKEN}\\t({t0},{t0 + 120},\\1c&HFFFFFF&){size}}}{t}{reset}")
        else:
            parts.append(f"{{\\i1}}{t}{{\\i0}}" if w["emph"] else t)
    return head + " ".join(parts)


def create_captions(words, style: str, ass_path: str):
    """Tulis subtitle ASS kinetik dari kata bertimestamp (sudah termasuk lead-in)."""
    cs = CAPTION_STYLES[style]
    phrases = group_phrases(words, cs["max_words"])
    lines, prev_end = [], 0.0
    for i, p in enumerate(phrases):
        start = max(p[0]["start"] - 0.08, prev_end)
        nxt = phrases[i + 1][0]["start"] - 0.08 if i + 1 < len(phrases) else None
        end = p[-1]["end"] + cs["hold"]
        if nxt is not None:
            end = nxt if nxt - p[-1]["end"] <= JOIN_GAP else min(end, nxt)
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{caption_text(p, start, style)}")
        prev_end = end
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER.format(style=cs["style"]))
        f.write("\n".join(lines) + "\n")
    print(f"[+] Teks kinetik {style}: {len(phrases)} frasa")

# ---------------------------------------------------------------- Musik & mix

# Kevin MacLeod (incompetech.com), CC BY 4.0. Mood per trek dipilih dari judul/karakter trek;
# ponytail: daftar statis, ganti dengan kurasi telinga bila ada trek yang terasa tidak cocok.
MUSIC_URL = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/{}.mp3"
MUSIC = {
    "dark_epic": ["Crossing the Chasm", "Heroic Age", "Impact Prelude", "Despair and Triumph"],
    "dark_reflective": ["Lightless Dawn", "Long Note Four", "Long Note Two", "Dark Times", "Echoes of Time v2"],
    "soft_hopeful": ["Inspired", "Healing", "Clean Soul", "Dreamer", "Ascending the Vale"],
    "soft_melancholic": ["Heartbreaking", "Sad Trio", "At Rest", "Lasting Hope", "Touching Moments Two - Higher"],
}
FALLBACK_BGM = "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=sad-soul-piano-ambient-112491.mp3"


def prepare_music(mood: str, output_path: str):
    """Unduh satu trek sesuai mood; kembalikan teks kredit (None untuk nada cadangan)."""
    titles = random.sample(MUSIC[mood], len(MUSIC[mood]))
    sources = [(MUSIC_URL.format(requests.utils.quote(t)), f'"{t}" by Kevin MacLeod (incompetech.com), CC BY 4.0')
               for t in titles] + [(FALLBACK_BGM, "Music: Pixabay")]
    for url, credit in sources:
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            if r.status_code == 200 and len(r.content) > 100_000:
                with open(output_path, "wb") as f:
                    f.write(r.content)
                print(f"[+] Musik ({mood}): {credit}")
                return credit
        except Exception as e:
            print(f"[!] Musik {url[-50:]} gagal: {e}")
    print("[!] Semua musik gagal diunduh, memakai nada drone cadangan")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=110:duration=60",
                    "-af", "volume=0.08,lowpass=f=300", output_path], check=True)
    return None

# Parameter ducking: musik turun saat narator bicara, naik lagi saat jeda
BGM_VOLUME = 0.20        # level musik saat narator diam
DUCK_THRESHOLD = 0.02    # ambang (amplitudo linear) narasi yang memicu penurunan musik
DUCK_RATIO = 8
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 600
LEAD_IN = 0.4            # detik hening sebelum narator mulai
TAIL = 1.8               # detik musik setelah kalimat terakhir


def build_audio_filter(narr_idx: int = 1, bgm_idx: int = 2, out_label: str = "a") -> str:
    """Narasi tetap penuh; musik dikompres sidechain oleh narasi lalu dicampur tanpa normalisasi."""
    # narasi: dual-mono (upmix biasa menurunkan 3 dB per kanal); musik: stereo 44,1 kHz
    narr_fmt = "aformat=sample_rates=44100:channel_layouts=mono,pan=stereo|c0=c0|c1=c0"
    bgm_fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    return (
        f"[{narr_idx}:a]{narr_fmt},asplit=2[narr][sc];"
        f"[{bgm_idx}:a]{bgm_fmt},volume={BGM_VOLUME}[bgm];"
        f"[bgm][sc]sidechaincompress=threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}"
        f":attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}[ducked];"
        f"[narr][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[{out_label}]"
    )


def prepare_narration_audio(raw: str, out_wav: str, total: float):
    """Geser narasi sebesar LEAD_IN, samakan loudness (-18 LUFS), lalu isi hening sampai `total`."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af",
                    f"adelay={int(LEAD_IN * 1000)}:all=1,loudnorm=I=-18:TP=-2:LRA=11,apad",
                    "-t", f"{total:.3f}", "-ac", "1", "-ar", "44100", out_wav], check=True)


def render_shorts_video(bg_video: str, narration_audio: str, bgm_audio: str, ass_subtitles: str,
                        final_output: str, total: float):
    print("[*] Merender video final (footage + narasi + musik ducking + teks kinetik)...")
    fade_out = max(total - 2.0, 0.0)
    filter_complex = (f"[0:v]subtitles=filename={ass_subtitles}:fontsdir={FONTS_DIR}[v];"
                      + build_audio_filter(out_label="mix")
                      + f";[mix]loudnorm=I=-15:TP=-1.5:LRA=5,afade=t=in:d=0.3,afade=t=out:st={fade_out:.2f}:d=2[a]")
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", bg_video,
        "-i", narration_audio,
        "-stream_loop", "-1", "-i", bgm_audio,  # musik diulang bila lebih pendek dari narasi
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        final_output
    ]
    subprocess.run(cmd, check=True)
    print(f"[+] Render sukses: {final_output} ({os.path.getsize(final_output) // 1024} KB)")


def make_preview(video: str, preview: str):
    """Versi 720p kecil untuk Telegram (batas unggah bot 50 MB)."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf", "scale=720:-2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k",
                    "-movflags", "+faststart", preview], check=True)


def loudness_report(path: str) -> str:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", r)
    lra = re.findall(r"LRA:\s+([\d.]+) LU", r)
    return f"{i[-1] if i else '?'} LUFS, LRA {lra[-1] if lra else '?'} LU"

# ---------------------------------------------------------------- Orkestrasi

def scene_spans(job: dict, total: float):
    """Rentang waktu tiap adegan: dari kata pertamanya sampai kata pertama adegan berikutnya."""
    starts = [0.0] + [scene[0]["start"] - 0.15 for scene in job["scenes"][1:]]
    return [(s, starts[i + 1] if i + 1 < len(starts) else total) for i, s in enumerate(starts)]


def render_job(job: dict, out_dir: str = OUTPUT_DIR) -> dict:
    """Render satu job ke out_dir/video.mp4 + preview.mp4 + meta.json. Kembalikan meta."""
    os.makedirs(out_dir, exist_ok=True)
    raw_narr = os.path.join(TEMP_DIR, "narration_raw.wav")
    narr = os.path.join(TEMP_DIR, "narration.wav")
    ass_path = os.path.join(TEMP_DIR, "captions.ass")
    bgm_path = os.path.join(TEMP_DIR, "music.mp3")
    bg_video = os.path.join(TEMP_DIR, "background.mp4")
    video = os.path.join(out_dir, "video.mp4")
    preview = os.path.join(out_dir, "preview.mp4")

    print(f"[*] Job baris {job['row']}: gaya {job['style']}, {len(job['scenes'])} adegan, mood {job['mood']}")
    duration, source = make_narration(job, raw_narr)
    words = [w for scene in job["scenes"] for w in scene]
    for w in words:
        w["start"] += LEAD_IN
        w["end"] += LEAD_IN
    total = LEAD_IN + duration + TAIL

    prepare_narration_audio(raw_narr, narr, total)
    create_captions(words, job["style"], ass_path)
    music_credit = prepare_music(job["mood"], bgm_path)
    footage_credits = prepare_scene_video(job, scene_spans(job, total), bg_video)
    render_shorts_video(bg_video, narr, bgm_path, ass_path, video, total)
    make_preview(video, preview)
    print(f"[*] Loudness akhir: {loudness_report(video)} (referensi: -21/-24 LUFS, LRA 3,5 LU)")

    meta = {
        "row": job["row"], "style": job["style"], "duration": round(total, 1), "tts": source,
        "caption": job["caption"], "hashtags": job["hashtags"], "yt_title": job["yt_title"],
        "credits": {"music": music_credit, "footage": footage_credits},
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def main():
    """Render manual: `python generator.py <baris>` atau QUOTE_INPUT (tanpa mengubah Sheet)."""
    quote = os.environ.get("QUOTE_INPUT", "").strip()
    if quote:
        row = {"row": "manual", "script": quote, "style": os.environ.get("STYLE_INPUT", DEFAULT_STYLE),
               "visuals": os.environ.get("VISUALS_INPUT", ""), "music_mood": os.environ.get("MOOD_INPUT", "")}
    else:
        service = get_sheets_service()
        if not service:
            sys.exit("Butuh QUOTE_INPUT atau kredensial Sheet")
        rows, _ = read_rows(service)
        wanted = sys.argv[1] if len(sys.argv) > 1 else None
        picks = [r for r in rows if (str(r["row"]) == wanted if wanted else r["status"].upper() == "READY")]
        if not picks:
            sys.exit("Tidak ada baris yang cocok")
        row = picks[0]
    meta = render_job(parse_job(row), os.path.join(OUTPUT_DIR, f"row-{row['row']}"))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
