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

async def generate_narration(text: str, output_path: str):
    import edge_tts
    print(f"[*] Menghasilkan audio TTS untuk narasi...")
    communicate = edge_tts.Communicate(
        text=text,
        voice="id-ID-ArdiNeural",
        rate="-5%",
        pitch="-3Hz"
    )
    await communicate.save(output_path)

def create_ass_subtitles(text: str, total_duration: float, ass_path: str):
    """Membuat subtitle karaoke bergaya profesional (muncul per 3-4 kata di tengah layar)"""
    print("[*] Merancang subtitle dinamis karaoke...")
    words = text.strip().split()
    total_words = len(words)
    if total_words == 0:
        return

    time_per_word = (total_duration - 1.0) / total_words
    chunk_size = 3
    chunks = []
    for i in range(0, total_words, chunk_size):
        chunk_words = words[i:i + chunk_size]
        start_time = i * time_per_word
        end_time = min(total_duration, (i + len(chunk_words)) * time_per_word)
        chunks.append({
            "start": start_time,
            "end": end_time,
            "text": " ".join(chunk_words).upper()
        })

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

def download_clip(url: str, dest: str) -> bool:
    """Unduh footage (maks ~15MB). True hanya jika hasilnya video yang bisa dibaca ffprobe."""
    if os.path.exists(dest) and probe_duration(dest) > 0:
        return True
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, stream=True)
        r.raise_for_status()
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                size += len(chunk)
                if size > 15 * 1024 * 1024:
                    break
        ok = probe_duration(dest) > 0
        print(f"[{'+' if ok else '!'}] Klip {os.path.basename(url)[:40]}: {size // 1024} KB, {'valid' if ok else 'tidak terbaca'}")
        return ok
    except Exception as e:
        print(f"[!] Gagal mengunduh {url} ({e})")
        return False

def make_segment(raw: str, seg_len: float, out_path: str):
    """Potong satu segmen vertikal 9:16 dari klip mentah, mulai dari titik acak."""
    clip_len = probe_duration(raw)
    cmd = ["ffmpeg", "-y"]
    if clip_len > seg_len + 0.5:
        cmd += ["-ss", f"{random.uniform(0, clip_len - seg_len - 0.25):.2f}"]
    cmd += ["-stream_loop", "-1", "-i", raw, "-t", f"{seg_len:.3f}", "-an",
            "-vf", VIDEO_FILTER, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out_path]
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)

def make_fallback_segment(seg_len: float, out_path: str):
    """Segmen cadangan jika klip gagal diunduh, agar jumlah klip dan durasi tetap utuh."""
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=0x0d1117:s=1080x1920:d={seg_len:.3f}:r=30",
        "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", out_path
    ], check=True, stderr=subprocess.DEVNULL)

def crossfade_segments(segments, seg_len: float, xf: float, offsets, output_path: str):
    cmd = ["ffmpeg", "-y"]
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
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)

def prepare_background_video(target_duration: float, output_path: str):
    """Susun 3-4 klip footage berbeda (9:16, 1080x1920) dengan crossfade halus."""
    total = target_duration + 1.5
    n, seg_len, xf, offsets = plan_sequence(total)
    urls = pick_clip_urls(n)
    print(f"[*] Menyusun {n} klip x {seg_len:.1f}s (crossfade {xf:.1f}s) untuk video {total:.1f}s...")

    segments = []
    for i, url in enumerate(urls):
        raw = os.path.join(TEMP_DIR, f"raw_{CINEMATIC_VIDEO_SOURCES.index(url)}.webm")
        seg_path = os.path.join(TEMP_DIR, f"seg_{i}.mp4")
        if download_clip(url, raw):
            make_segment(raw, seg_len, seg_path)
        else:
            print(f"[!] Klip {i + 1} memakai visual cadangan")
            make_fallback_segment(seg_len, seg_path)
        segments.append(seg_path)

    crossfade_segments(segments, seg_len, xf, offsets, output_path)
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

def render_shorts_video(bg_video: str, narration_audio: str, bgm_audio: str, ass_subtitles: str, final_output: str, duration: float):
    print("[*] Merender video final (Visual Bergerak + Audio Narasi + BGM Ducking + Karaoke Subtitle)...")
    
    # Filter Subtitle ASS + Audio mixing ducking
    filter_complex = (
        f"[0:v]subtitles={ass_subtitles}[v];"
        f"[2:a]volume=0.18[bgm];"
        f"[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", bg_video,
        "-i", narration_audio,
        "-i", bgm_audio,
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
    asyncio.run(generate_narration(quote, audio_path))
    cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    duration = float(subprocess.check_output(cmd_dur).decode().strip())

    # 2. Rancang Subtitle Dinamis (ASS)
    create_ass_subtitles(quote, duration, ass_path)

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
