#!/usr/bin/env python3
"""
TikTok Shorts Video Generator Engine v2.0
- Professional Cinematic Video Backgrounds (Direct Wikimedia / Stable CDN Streams)
- Dynamic Karaoke Bold Subtitles (ASS Format - Word/Phrase-by-Phrase Centered)
- Emotional Ambient Piano BGM with Automatic Audio Ducking
- Integration with Google Sheets
"""

import os
import sys
import json
import math
import random
import asyncio
import subprocess
import time
import requests

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1wQepTnnoZi0rO5oPKkP5Qq8dfIcwqiAPg1r9_tadLf4")
GCP_SA_KEY = os.environ.get("GCP_SERVICE_ACCOUNT_KEY", "")

OUTPUT_DIR = "output"
TEMP_DIR = "temp"
ASSETS_DIR = "assets"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

# Pustaka klip video bergerak nyata (Landscape/Portrait sinematik: kabut, hujan, ombak, hutan)
CINEMATIC_VIDEO_SOURCES = [
    # Hujan rintik di kaca & jalanan basah
    "https://upload.wikimedia.org/wikipedia/commons/c/c3/Rain_in_Kenwood_-_September_30_2023_-_Sarah_Stierch.webm",
    # Kabut pagi di atas danau dan hutan cemara
    "https://upload.wikimedia.org/wikipedia/commons/2/20/Morning_Fog_on_Lake_BRoll_10s.webm",
    # Pemandangan alam Aberfeldy
    "https://upload.wikimedia.org/wikipedia/commons/4/49/Nature_montage_around_Aberfeldy.webm"
]

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
    return build("sheets", "v4", credentials=creds)

def fetch_ready_quote():
    service = get_sheets_service()
    if not service:
        return None, None, None
    res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="Sheet1!A1:F50").execute()
    rows = res.get("values", [])
    for idx, r in enumerate(rows[1:], start=2):
        status = r[5] if len(r) > 5 else ""
        if status.strip().upper() == "READY":
            quote = r[0]
            env = r[1] if len(r) > 1 and r[1] else "cinematic dark moody rain"
            return idx, quote, env
    return None, None, None

def update_sheet_status(row_idx: int, video_url: str):
    service = get_sheets_service()
    if not service or not row_idx:
        return
    update_range = f"Sheet1!E{row_idx}:F{row_idx}"
    body = {"values": [[video_url, "DONE"]]}
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=update_range,
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()
    print(f"[+] Status baris {row_idx} berhasil diupdate ke 'DONE'!")

TICKS_PER_SEC = 10_000_000  # edge-tts melaporkan offset/durasi dalam satuan 100 ns

async def generate_narration(text: str, output_path: str):
    """Simpan audio narasi dan kembalikan event batas kata/kalimat (detik) untuk sinkronisasi subtitle."""
    import edge_tts
    print(f"[*] Menghasilkan audio TTS untuk narasi...")
    kwargs = dict(text=text, voice="id-ID-ArdiNeural", rate="-5%", pitch="-3Hz")
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
MAX_SUBTITLE_GAP = 0.35  # jeda ucapan lebih pendek dari ini tidak mengosongkan layar

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
    """Hasilkan [(kata, mulai, selesai)] dengan sumber waktu terbaik yang tersedia.

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

def create_ass_subtitles(text: str, total_duration: float, ass_path: str, events=None):
    """Membuat subtitle profesional (3 kata per tampilan di tengah layar), tersinkron dengan ucapan."""
    print("[*] Merancang subtitle dinamis...")
    timings = build_word_timings(text, events or [], total_duration)
    if not timings:
        return

    chunk_size = 3
    chunks = []
    for i in range(0, len(timings), chunk_size):
        group = timings[i:i + chunk_size]
        shown = " ".join(w for w, _, _ in group).replace("{", "(").replace("}", ")")  # cegah tag override ASS
        chunks.append({"start": group[0][1], "end": group[-1][2], "text": shown.upper()})
    for cur, nxt in zip(chunks, chunks[1:] + [None]):
        if nxt is None:
            cur["end"] += 0.3
        elif nxt["start"] - cur["end"] <= MAX_SUBTITLE_GAP:
            cur["end"] = nxt["start"]  # sambung langsung ke tampilan berikutnya
        else:
            cur["end"] = min(cur["end"] + 0.15, nxt["start"])  # jeda panjang: layar boleh kosong

    def sec_to_ass(s):
        hrs = int(s // 3600)
        mins = int((s % 3600) // 60)
        secs = int(s % 60)
        cs = int((s - int(s)) * 100)
        return f"{hrs:d}:{mins:02d}:{secs:02d}.{cs:02d}"

    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,64,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,920,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for c in chunks:
            f.write(f"Dialogue: 0,{sec_to_ass(c['start'])},{sec_to_ass(c['end'])},Default,,0,0,0,,{c['text']}\n")

# Parameter sequencing multi-klip
MIN_CLIPS = 3          # jumlah klip minimum dalam satu video
MAX_CLIPS = 4          # jumlah klip maksimum
SECONDS_PER_CLIP = 9   # target durasi tampil per klip (menentukan jumlah klip)
CROSSFADE = 0.8        # durasi transisi antar klip (detik)
TRANSITIONS = ["fade", "dissolve", "fadeblack"]  # transisi halus, dipakai bergantian
VIDEO_FILTER = (
    "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
    "setsar=1,fps=30,eq=brightness=-0.15:contrast=1.2,vignette=PI/4,format=yuv420p"
)

def plan_sequence(total: float):
    """Hitung jumlah klip, durasi tiap segmen, durasi crossfade, dan offset xfade.

    Panjang hasil = n*seg - (n-1)*xf = total, jadi video akhir tepat sepanjang `total`.
    """
    n = max(MIN_CLIPS, min(MAX_CLIPS, math.ceil(total / SECONDS_PER_CLIP)))
    xf = min(CROSSFADE, total / (3 * n))  # untuk video sangat pendek, perkecil transisi
    seg = (total + (n - 1) * xf) / n
    offsets = [round(i * (seg - xf), 3) for i in range(1, n)]
    return n, seg, xf, offsets

def pick_clip_urls(n: int):
    """Pilih n URL: tanpa pengulangan selama pool cukup, tidak pernah dua klip sama berurutan."""
    pool = list(CINEMATIC_VIDEO_SOURCES)
    picks = random.sample(pool, min(n, len(pool)))
    while len(picks) < n:
        picks.append(random.choice([u for u in pool if u != picks[-1]] or pool))
    return picks

def probe_duration(path: str) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stderr=subprocess.DEVNULL).decode().strip()
        return float(out)
    except Exception:
        return 0.0

# Wikimedia menolak (HTTP 429/403) User-Agent generik dari IP datacenter; kebijakannya meminta
# UA deskriptif dengan kontak: https://meta.wikimedia.org/wiki/User-Agent_policy
USER_AGENT = "TikTokShortsVideoEngine/2.1 (+https://github.com/marthen-wq/tiktok-video-engine) python-requests"
DOWNLOAD_ATTEMPTS = 3
MAX_RETRY_WAIT = 20  # detik
_failed_urls = set()  # URL yang sudah gagal di run ini tidak dicoba lagi untuk klip berikutnya

def _retry_wait(resp, attempt: int) -> float:
    try:
        return min(MAX_RETRY_WAIT, float(resp.headers.get("Retry-After", "")))
    except ValueError:
        return min(MAX_RETRY_WAIT, 2.0 * 2 ** attempt)

WIKIMEDIA_PREFIX = "https://upload.wikimedia.org/wikipedia/commons/"
TRANSCODE_KEYS = ["1080p.vp9.webm", "720p.vp9.webm", "720p.webm"]

def footage_candidates(url: str):
    """URL unduhan berurutan: versi transcode Wikimedia dulu, file asli terakhir.

    File asli di Commons sering 4K berbitrate sangat tinggi: 15MB pertama hanya berisi
    ~1-2 detik gambar (terlihat di run #4), sehingga segmen 9 detik menjadi loop tersendat.
    """
    if not url.startswith(WIKIMEDIA_PREFIX):
        return [url]
    path = url[len(WIKIMEDIA_PREFIX):]          # c/c3/Nama.webm
    name = path.rsplit("/", 1)[-1]
    base = f"{WIKIMEDIA_PREFIX}transcoded/{path}/{name}"
    return [f"{base}.{key}" for key in TRANSCODE_KEYS] + [url]

def _download_one(url: str, dest: str) -> str:
    """Satu kandidat URL. Hasil: 'ok', 'missing' (coba kandidat lain), atau 'limited' (berhenti)."""
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
    """Unduh footage (maks ~15MB) dari kandidat terbaik. True jika hasilnya video yang terbaca ffprobe."""
    if os.path.exists(dest) and probe_duration(dest) > 0:
        return True
    if url in _failed_urls:
        return False
    for candidate in footage_candidates(url):
        result = _download_one(candidate, dest)
        if result == "ok":
            return True
        if result == "limited":
            break
    _failed_urls.add(url)
    return False

def remux_clip(raw: str, dest: str) -> bool:
    """Salin ulang stream video ke MKV agar durasi sesuai data yang benar-benar terunduh.

    Unduhan yang dipotong di ~15MB tetap membawa header durasi penuh (mis. 120 s padahal
    datanya 16 s), sehingga titik mulai acak bisa jatuh di luar data yang ada.
    """
    if os.path.exists(dest) and probe_duration(dest) > 0:
        return True
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-map", "0:v:0", "-c", "copy", dest])
    real = probe_duration(dest)
    print(f"[*] Durasi footage terpakai: {real:.1f}s (header: {probe_duration(raw):.1f}s)")
    return real > 0

SEGMENT_TOLERANCE = 0.15  # toleransi pembulatan frame saat memeriksa panjang segmen (detik)
MAX_SLOWDOWN = 2.0        # klip lebih pendek dari segmen diperlambat sampai 2x; di atas itu baru di-loop

def encode_segment(clip: str, start, seg_len: float, out_path: str, slow: float = 1.0):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.2f}"]
    vf = VIDEO_FILTER if slow <= 1.0 else f"setpts={slow:.4f}*PTS,{VIDEO_FILTER}"
    cmd += ["-stream_loop", "-1", "-i", clip, "-t", f"{seg_len:.3f}", "-an",
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out_path]
    subprocess.run(cmd, check=True)

def make_segment(clip: str, seg_len: float, out_path: str) -> bool:
    """Potong satu segmen vertikal 9:16 dari klip.

    Klip panjang: mulai dari titik acak. Klip lebih pendek dari segmen: diperlambat agar pas
    (loop membuat lompatan gambar yang kasar, terlihat pada klip Rain 5,9 s di run #5).
    Bila hasilnya kurang panjang, diulang dari awal klip dengan loop.
    """
    clip_len = probe_duration(clip)
    attempts = []
    if clip_len > seg_len + 0.5:
        attempts.append((random.uniform(0, clip_len - seg_len - 0.25), 1.0))
    elif 0 < clip_len and seg_len / clip_len <= MAX_SLOWDOWN:
        attempts.append((None, seg_len / clip_len * 1.02))  # sedikit lebih lambat agar loop tidak tersentuh
    attempts.append((None, 1.0))
    name = os.path.basename(out_path)
    for start, slow in attempts:
        if slow > 1.0:
            label = f"diperlambat {1 / slow:.2f}x"
        else:
            label = f"mulai {start:.1f}s" if start is not None else "dari awal (loop)"
        try:
            encode_segment(clip, start, seg_len, out_path, slow)
        except subprocess.CalledProcessError as e:
            print(f"[!] Segmen {name} gagal di-encode ({label}): {e}")
            continue
        got = probe_duration(out_path)
        if got >= seg_len - SEGMENT_TOLERANCE:
            print(f"[+] Segmen {name}: {label}, {got:.2f}s")
            return True
        print(f"[!] Segmen {name} terlalu pendek: {got:.2f}s dari {seg_len:.2f}s ({label})")
    return False

def make_fallback_segment(seg_len: float, out_path: str):
    """Segmen cadangan jika klip gagal diunduh, agar jumlah klip dan durasi tetap utuh."""
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c=0x0d1117:s=1080x1920:d={seg_len:.3f}:r=30",
        "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", out_path
    ], check=True)

def crossfade_segments(segments, seg_len: float, xf: float, offsets, output_path: str):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for seg in segments:
        cmd += ["-i", seg]
    if len(segments) == 1:
        graph, last = "", "0:v"
    else:
        parts, last = [], "0:v"
        for i, off in enumerate(offsets, start=1):
            tr = TRANSITIONS[(i - 1) % len(TRANSITIONS)]
            parts.append(f"[{last}][{i}:v]xfade=transition={tr}:duration={xf:.3f}:offset={off}[v{i}]")
            last = f"v{i}"
        graph = ";".join(parts)
    if graph:
        cmd += ["-filter_complex", graph, "-map", f"[{last}]"]
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

def prepare_background_video(target_duration: float, output_path: str):
    """Susun 3-4 klip footage berbeda (9:16, 1080x1920) dengan crossfade halus."""
    total = target_duration + 1.5
    n, seg_len, xf, offsets = plan_sequence(total)
    urls = pick_clip_urls(n)
    print(f"[*] Menyusun {n} klip x {seg_len:.1f}s (crossfade {xf:.1f}s) untuk video {total:.1f}s...")

    segments, real_clips = [], 0
    for i, url in enumerate(urls):
        idx = CINEMATIC_VIDEO_SOURCES.index(url)
        raw = os.path.join(TEMP_DIR, f"raw_{idx}.webm")
        clip = os.path.join(TEMP_DIR, f"clip_{idx}.mkv")
        seg_path = os.path.join(TEMP_DIR, f"seg_{i}.mp4")
        ok = download_clip(url, raw) and remux_clip(raw, clip) and make_segment(clip, seg_len, seg_path)
        real_clips += ok
        if not ok:
            print(f"[!] Klip {i + 1} memakai visual cadangan")
            make_fallback_segment(seg_len, seg_path)
        segments.append(seg_path)

    if real_clips == 0:
        # Keputusan pemilik: tanpa footage sama sekali, run harus gagal (baris Sheet tetap READY)
        raise RuntimeError("Semua footage gagal diunduh/diproses; video tidak dirender")

    crossfade_segments(segments, seg_len, xf, offsets, output_path)
    extend_to_duration(output_path, total)
    print(f"[+] Background multi-klip siap: {probe_duration(output_path):.1f}s")

def prepare_bgm(output_path: str):
    """Menyiapkan musik latar instrumental piano emosional"""
    if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
        return
    print("[*] Menyiapkan Background Music (BGM)...")
    url = "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=sad-soul-piano-ambient-112491.mp3"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200 and len(r.content) > 100000:
            with open(output_path, "wb") as f:
                f.write(r.content)
            return
    except Exception:
        pass
    # Fallback: Buat nada drone ambient lembut jika offline
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "sine=frequency=110:duration=60",
        "-af", "volume=0.08,lowpass=f=300",
        output_path
    ], check=True)

# Parameter ducking: musik turun saat narator bicara, naik lagi saat jeda
BGM_VOLUME = 0.20        # level musik saat narator diam
DUCK_THRESHOLD = 0.02    # ambang (amplitudo linear) narasi yang memicu penurunan musik
DUCK_RATIO = 8
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 600

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

def render_shorts_video(bg_video: str, narration_audio: str, bgm_audio: str, ass_subtitles: str, final_output: str, duration: float):
    print("[*] Merender video final (Visual Bergerak + Audio Narasi + BGM Ducking + Subtitle)...")

    filter_complex = f"[0:v]subtitles={ass_subtitles}[v];" + build_audio_filter()

    cmd = [
        "ffmpeg", "-y",
        "-i", bg_video,
        "-i", narration_audio,
        "-stream_loop", "-1", "-i", bgm_audio,  # musik diulang bila lebih pendek dari narasi
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-t", str(duration + 1.2),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        final_output
    ]
    subprocess.run(cmd, check=True)
    print(f"[+] Render sukses: {final_output} ({os.path.getsize(final_output) // 1024} KB)")

def main():
    row_idx = None
    quote_override = os.environ.get("QUOTE_INPUT", "").strip()

    if quote_override:
        quote = quote_override
        print(f"[*] Menjalankan video dengan quote input manual:\n{quote}")
    else:
        row_idx, quote, env = fetch_ready_quote()
        if not quote:
            print("[*] Tidak ada baris READY, menggunakan quote motivasi teruji...")
            quote = "Kamu tidak sedang tertinggal, kamu hanya sedang ditempa di ruang yang tidak dilihat orang. Berhenti membandingkan langkah awalmu dengan panggung orang lain."

    video_name = f"shorts_{row_idx or 'motivasi'}.mp4"
    audio_path = os.path.join(TEMP_DIR, "narration.mp3")
    ass_path = os.path.join(TEMP_DIR, "subtitles.ass")
    bgm_path = os.path.join(ASSETS_DIR, "piano_ambient.mp3")
    bg_video = os.path.join(TEMP_DIR, "bg_motion.mp4")
    final_video = os.path.join(OUTPUT_DIR, video_name)

    # 1. Generate Audio Narasi
    events = asyncio.run(generate_narration(quote, audio_path))
    cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    duration = float(subprocess.check_output(cmd_dur).decode().strip())

    # 2. Rancang Subtitle Dinamis (ASS)
    create_ass_subtitles(quote, duration, ass_path, events)

    # 3. Video Footage Bergerak Asli & Musik Latar
    prepare_bgm(bgm_path)
    prepare_background_video(duration, bg_video)

    # 4. Render Video Akhir
    render_shorts_video(bg_video, audio_path, bgm_path, ass_path, final_video, duration)

    # 5. Update Status Google Sheet jika relevan
    if row_idx:
        update_sheet_status(row_idx, f"GitHub Artifact: {video_name}")

if __name__ == "__main__":
    main()
