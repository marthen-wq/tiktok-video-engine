# ARCHITECTURE — TikTok Shorts Video Engine

Versi lengkap. Untuk ringkasan keputusan kritis lihat [ARCHITECTURE-ESSENTIALS.md](ARCHITECTURE-ESSENTIALS.md).
Basis kode: `generator.py` v2.0 + sequencing multi-klip (v2.1).

## 1. Gambaran sistem

```
Google Sheets (antrean, F = READY)
        │  Sheets API v4 (service account)
        ▼
GitHub Actions: generate.yml  (ubuntu-latest, Python 3.10, timeout 15 menit)
        │
        ▼
generator.py ── main()
   1. fetch_ready_quote()          → (row_idx, quote, env)   atau QUOTE_INPUT (manual)
   2. generate_narration()         → temp/narration.mp3      (edge-tts)
   3. ffprobe                      → duration (detik)
   4. create_ass_subtitles()       → temp/subtitles.ass
   5. prepare_bgm()                → assets/piano_ambient.mp3
   6. prepare_background_video()   → temp/bg_motion.mp4      (3–4 klip + crossfade)
   7. render_shorts_video()        → output/shorts_<row>.mp4
   8. update_sheet_status()        → E = referensi, F = DONE
        │
        ▼
actions/upload-artifact (tiktok-shorts-video, 7 hari)
```

Eksekusi serial dalam satu proses Python. Tidak ada server, antrean pesan, atau database; Google Sheet adalah antrean dan sekaligus penyimpan status.

## 2. Komponen

| Komponen | File / fungsi | Tanggung jawab |
|---|---|---|
| Pemicu | `.github/workflows/generate.yml` | `workflow_dispatch` (input `quote_override`) dan `repository_dispatch` (`generate-video`); siapkan Python, FFmpeg, font; jalankan generator; unggah artifact |
| Antrean | `fetch_ready_quote`, `update_sheet_status` | Baca `Sheet1!A1:F50`, ambil baris `READY` pertama; tulis `E:F` |
| Suara | `generate_narration` | edge-tts `id-ID-ArdiNeural`, rate `-5%`, pitch `-3Hz`, `boundary="WordBoundary"`; mengembalikan event waktu kata (detik) |
| Subtitle | `build_word_timings`, `spread_words`, `create_ass_subtitles` | Waktu kata dari event TTS, bagi per 3 kata, tulis file ASS |
| Visual | `plan_sequence`, `pick_clip_urls`, `download_clip`, `make_segment`, `make_fallback_segment`, `crossfade_segments`, `prepare_background_video` | Susun 3–4 klip menjadi satu background 9:16 |
| Audio latar | `prepare_bgm` | Unduh piano ambient; fallback nada sinus 110 Hz |
| Render | `build_audio_filter`, `render_shorts_video` | Bakar subtitle, ducking sidechain narasi → musik, encode H.264/AAC |
| Tes | `tests/test_sequencing.py` | Uji logika sequencing dan render dengan klip sintetis |

## 3. Sequencing multi-klip (v2.1)

Tujuan: video ~30 detik berisi 3–4 pemandangan berbeda yang berganti halus.

Parameter (konstanta di `generator.py`): `MIN_CLIPS=3`, `MAX_CLIPS=4`, `SECONDS_PER_CLIP=9`, `CROSSFADE=0.8`.

Perhitungan `plan_sequence(total)`, dengan `total = durasi narasi + 1.5 s`:

```
n      = clamp(ceil(total / 9), 3, 4)
xf     = min(0.8, total / (3n))             # transisi mengecil untuk video sangat pendek
seg    = (total + (n-1)·xf) / n             # durasi tiap segmen
offset_i = i · (seg − xf),  i = 1..n−1      # titik mulai xfade ke-i
```

Panjang hasil `n·seg − (n−1)·xf = total`, jadi tepat sama dengan target. Contoh 30 detik: `total=31.5` → 4 klip × 8,475 s, crossfade 0,8 s, offset 7,675 / 15,35 / 23,025.

Langkah per video:
1. `pick_clip_urls(n)` memilih URL tanpa pengulangan selama pool cukup; bila pool lebih kecil dari `n` (saat ini pool = 3, `n` bisa 4), klip dipakai ulang tetapi tidak pernah berurutan.
2. `download_clip` mengunduh (maks ~15 MB, `raise_for_status`, divalidasi `ffprobe`). Klip dipakai ulang dari cache `temp/raw_<i>.webm` bila sudah ada.
3. `make_segment` memotong `seg` detik dari titik acak klip, lalu: scale + crop 1080x1920, `fps=30`, `eq` (brightness -0.15, contrast 1.2), `vignette`, `format=yuv420p`. Klip pendek di-loop.
4. Gagal unduh → `make_fallback_segment` (warna polos `0x0d1117`) menggantikan hanya klip itu, jadi jumlah klip dan durasi tetap utuh.
5. `crossfade_segments` merangkai semua segmen dengan filter `xfade`, transisi bergantian `fade`, `dissolve`, `fadeblack`.

Hasil uji (`tests/test_sequencing.py`): 4 klip berwarna berbeda untuk 30 detik, warna dominan berganti di tiap segmen, durasi 31,5 s, resolusi 1080x1920. Yang belum teruji: unduhan nyata dari Wikimedia (diblokir di sandbox pengembangan).

### 3b. Sinkronisasi subtitle dan ducking audio

**Subtitle.** `generate_narration` meminta `boundary="WordBoundary"` ke edge-tts dan menampung event (offset/durasi dalam tick 100 ns, dikonversi ke detik). `build_word_timings` memilih sumber waktu terbaik:
1. `WordBoundary`: waktu ucapan sebenarnya. Jumlah event sama dengan jumlah kata → kata asli (dengan tanda baca) dipakai.
2. `SentenceBoundary`: kata dibagi proporsional panjang karakter di dalam tiap kalimat, batas kalimat tepat.
3. Tanpa event: seluruh durasi audio dibagi proporsional panjang kata (+ bobot jeda setelah tanda baca).

Tiap tampilan 3 kata muncul saat kata pertamanya diucapkan. Jeda ucapan ≤ 0,35 s disambung ke tampilan berikutnya; jeda lebih panjang mengosongkan layar. Tanda `{` `}` dari quote diganti agar tidak menjadi tag ASS.

**Ducking.** `build_audio_filter`: narasi dijadikan dual-mono stereo lalu dipecah (`asplit`) menjadi jalur campuran dan jalur sidechain; musik (`volume=BGM_VOLUME`) dikompres oleh jalur sidechain (`sidechaincompress`, threshold 0,02, ratio 8, attack 20 ms, release 600 ms), lalu keduanya dicampur dengan `amix=normalize=0` (narasi tidak dibagi dua; butuh FFmpeg ≥ 4.4, runner `ubuntu-latest` memakai 6.1). Musik di-loop bila lebih pendek dari narasi. Pada nada uji musik turun ~19 dB saat narasi aktif dan level narasi tidak berubah.

## 4. Model data

### 4.1 Google Sheet `Sheet1` (antrean)

| Kolom | Isi | Dibaca | Ditulis | Catatan |
|---|---|---|---|---|
| A | `quote`, kalimat narasi | ya | tidak | wajib |
| B | `environment`, tema visual | ya | tidak | default `"cinematic dark moody rain"`; **belum dipakai** memilih footage |
| C, D | belum didefinisikan | tidak | tidak | diabaikan kode |
| E | `video_url` | tidak | ya | saat ini teks `GitHub Artifact: <nama file>`, bukan tautan |
| F | `status` | ya | ya | `READY` → `DONE`; pencocokan tidak peka huruf besar/kecil |

Baris 1 adalah header. Rentang baca `A1:F50` sehingga hanya 49 baris data pertama yang terlihat. Siklus status: `READY` → (render) → `DONE`. Tidak ada status `ERROR` atau `PROCESSING`; baris yang gagal tetap `READY` dan diambil lagi di run berikutnya.

### 4.2 Struktur data internal

```
Quote           : str                              # kalimat utuh
Narration       : file mp3 + duration: float       # duration dari ffprobe
BoundaryEvent   : {kind: WordBoundary|SentenceBoundary, text: str, start: float, end: float}  # detik
WordTiming      : (word: str, start: float, end: float)
SubtitleChunk   : {start: float, end: float, text: str}   # 3 kata, huruf kapital
SequencePlan    : (n: int, seg: float, xf: float, offsets: list[float])
ClipSource      : str                              # URL di CINEMATIC_VIDEO_SOURCES
Segment         : temp/seg_<i>.mp4                 # 1080x1920, 30 fps, tanpa audio
```

### 4.3 Berkas dan direktori

| Path | Isi | Dilacak git |
|---|---|---|
| `output/` | MP4 akhir `shorts_<row|motivasi>.mp4` | tidak (dibuat saat run) |
| `temp/` | narasi, ASS, klip mentah, segmen, background | tidak |
| `assets/` | `piano_ambient.mp3` (cache BGM) | tidak |
| `tests/` | tes sequencing | ya |

### 4.4 Konfigurasi (environment)

| Variabel | Sumber | Fungsi |
|---|---|---|
| `SPREADSHEET_ID` | Secret | ID Sheet (default hard-coded di kode) |
| `GCP_SERVICE_ACCOUNT_KEY` | Secret | JSON service account; tanpa ini Sheet dilewati |
| `QUOTE_INPUT` | input workflow | Kalimat manual; melewati Sheet |
| `OMNIROUTE_URL`, `OMNIROUTE_KEY` | Secret | Disiapkan untuk gateway LLM; **belum dipakai kode** |
| `GITHUB_TOKEN` | otomatis | Disediakan ke proses, belum dipakai |

## 5. Tech stack

| Lapisan | Pilihan | Alasan |
|---|---|---|
| Orkestrasi | GitHub Actions `ubuntu-latest` | Serverless, gratis untuk repo publik / kuota privat |
| Bahasa | Python 3.10 | Ekosistem edge-tts dan Google API |
| TTS | `edge-tts` ≥ 7.2, suara `id-ID-ArdiNeural` | Gratis, suara Indonesia berwibawa |
| Video / audio | FFmpeg + libass | Satu alat untuk scale, xfade, subtitle, mix, encode |
| Subtitle | ASS (Advanced SubStation Alpha) | Kontrol gaya, posisi, outline; dibakar via filter `subtitles` |
| Antrean | Google Sheets API v4 (`google-api-python-client`, `google-auth`) | UI siap pakai untuk mengisi antrean |
| HTTP | `requests` | Unduh footage dan BGM |
| Font | DejaVu Sans Bold (dipakai style ASS); `fonts-montserrat` ikut terpasang tetapi belum dipakai | Tersedia di runner |
| Output | H.264 (`libx264`, crf 22) + AAC 192k, `yuv420p` | Kompatibel TikTok / Shorts |

`requirements.txt` juga memuat `whisper-timestamped`, `moviepy`, `pillow`, `numpy`, `cryptography`. Tidak satu pun diimpor oleh `generator.py` saat ini; `whisper-timestamped` menarik PyTorch dan memperlambat install.

## 6. Perilaku saat gagal

| Kegagalan | Perilaku sekarang |
|---|---|
| Tidak ada `GCP_SERVICE_ACCOUNT_KEY` | Sheet dilewati, memakai quote bawaan di kode |
| Tidak ada baris `READY` | Memakai quote bawaan; status tidak diubah |
| Klip footage gagal / bukan video | Segmen itu diganti warna polos; sisanya tetap |
| Semua klip gagal | Video berupa warna polos dengan crossfade |
| BGM gagal diunduh | Nada sinus 110 Hz, volume rendah |
| FFmpeg error | `check=True` melempar exception; run merah |
| Update Sheet gagal | Exception; MP4 tetap tidak terunggah karena langkah upload berikutnya tidak jalan |

## 7. Keamanan

- Kredensial hanya lewat GitHub Secrets; jangan commit JSON service account.
- Scope Sheets: `spreadsheets` (baca-tulis). Cukup untuk fungsi saat ini; bagikan Sheet hanya ke service account yang bersangkutan.
- Teks quote masuk ke file ASS dan ke argumen edge-tts; tidak pernah dieksekusi shell (`subprocess` memakai daftar argumen).
- Unduhan dibatasi ~15 MB per klip dan timeout 30 detik.

## 8. Pengujian

- Otomatis, offline: `python3 -m unittest discover -s tests -v` (butuh `ffmpeg`, `requests`). Mencakup rencana sequencing, pergantian klip, durasi, resolusi, dan fallback.
- Manual, nyata: jalankan workflow (lihat bagian "How to Run & Test" di `CLAUDE.md`).
- Belum ada tes untuk TTS, Sheets, dan subtitle karena membutuhkan jaringan / kredensial.

## 9. Celah yang diketahui

1. Level ducking (`BGM_VOLUME`, `DUCK_*`) baru diukur dengan nada uji, belum didengar dengan musik dan suara asli.
2. Subtitle tersinkron per tampilan 3 kata; belum ada highlight kata per kata (`\k`). Apakah `id-ID-ArdiNeural` mengirim event `WordBoundary` belum terverifikasi; bila tidak, cadangan otomatis dipakai dan tercatat di log.
3. Kolom B (tema) dibaca tetapi tidak memengaruhi pemilihan footage.
4. Kolom E berisi teks, bukan tautan; `DONE` ditulis sebelum artifact diunggah.
5. (selesai) BGM kini di-loop dengan `-stream_loop -1`.
6. URL footage dan BGM belum terverifikasi dari runner; User-Agent `Mozilla/5.0` tidak sesuai kebijakan Wikimedia.
7. Pool footage hanya 3 URL sementara video bisa memakai 4 klip.
8. Secret `OMNIROUTE_*` dan dependensi berat belum dipakai.
9. `repository_dispatch` tidak meneruskan `client_payload` sebagai quote.
