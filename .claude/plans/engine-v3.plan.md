# Plan: TikTok Shorts Engine v3 — otomasi penuh dari ide sampai posting

**Sumber intent**: wawancara 2026-10-09 (dikonfirmasi user)
**Kompleksitas**: Large
**Status**: DRAFT — menunggu persetujuan

## Ringkasan

Setiap hari 08:00 WIB Gemini Spark meriset tren FYP dan menawarkan 3 ide; ide yang dipilih user ditulis ke Sheet. Mesin merender video berbahasa Inggris (gaya Dark Stoic atau Soft Healing, 20 dtk–2 mnt) dengan narasi ekspresif ber-jeda, teks kinetik kata-per-kata, dan footage metafora per adegan. Preview dikirim ke Telegram; setelah user menekan ✅, video diposting ke TikTok dan YouTube Shorts di slot jam terbaik. Biaya Rp0.

## Alur target

```
08:00 WIB  Gemini Spark: riset tren FYP → 3 ide → user pilih di Spark
              ↓ Spark menulis 1 baris ke Sheet1 (status READY)
tick (cron 15 mnt, GitHub Actions)  scheduler.py
  ├─ ada READY      → render (generator.py) → status PREVIEW → kirim ke Telegram
  ├─ tombol Telegram → ✅ APPROVED + jadwal slot berikutnya | 🔁 READY lagi | ❌ REJECTED
  └─ slot tiba      → posting TikTok + YouTube → status POSTED
```

## Keputusan yang perlu user ambil

| # | Keputusan | Rekomendasi | Alasan |
|---|---|---|---|
| D1 | Repo publik atau tetap privat | **Jadikan publik** | Repo privat hanya dapat 2.000 menit Actions/bulan; cron 15 menit saja menghabiskan ~2.880 menit. Repo publik = menit tak terbatas, satu basis kode Python. Secrets tetap aman (GitHub Secrets). Alternatif privat: semua penjadwalan dipindah ke Google Apps Script (gratis) — lebih banyak bagian bergerak. Repo publik juga bisa memakai GitHub Pages gratis untuk halaman Privacy Policy/ToS yang diminta TikTok. |
| D2 | Zona waktu audiens | **AS bagian timur (ET)** | Audiens TikTok/Shorts berbahasa Inggris terbesar. Slot default: 15:00 dan 20:00 ET (= 02:00 dan 07:00 WIB saat musim panas AS; 03:00 dan 08:00 WIB mulai Nov). Bisa diubah di config. |

## Riset: pilihan layanan (semua gratis)

| Kebutuhan | Pilihan | Sumber public-apis | Catatan |
|---|---|---|---|
| Narasi emosional | **Gemini TTS** (model TTS terbaru di AI Studio, mis. `gemini-3.8-flash-tts`) dengan *director's notes* + tag jeda/emosi | Google Gemini (Machine Learning) | Kuota gratis TTS tidak dipublikasikan, harus dicek di AI Studio → spike S1. Cadangan: **Kokoro-82M** (Apache-2.0, jalan di CPU) + jeda disisipkan manual. |
| Waktu per kata (teks kinetik) | **whisper-timestamped** (sudah ada di `requirements.txt`) untuk forced alignment audio Gemini | — | Gemini TTS tidak mengembalikan timestamp kata. |
| Footage sesuai narasi | **Pexels API** (video+foto, 200 req/jam) utama, **Pixabay API** cadangan | Photography: Pexels, Pixabay | Spark menulis kata kunci visual per adegan. Pool Wikimedia lama tetap jadi fallback terakhir. |
| Musik | Library kurasi di `assets/music/<mood>/` dari **Freesound** (filter CC0) dan **Jamendo** (CC-BY, atribusi di caption) | Music: Freesound, Jamendo | Dikurasi sekali, di-commit. Menghindari URL CDN Pixabay yang sementara (masalah lama). |
| Preview + persetujuan | **Telegram Bot API** (`sendVideo` + inline keyboard, `getUpdates`) | Social: Telegram Bot | Tanpa server: dibaca oleh tick cron. |
| Posting TikTok | **TikTok Content Posting API** | Social: TikTok | Sebelum audit: Direct Post hanya ke akun *privat* → pakai **Upload to Inbox** (draft; user ketuk notifikasi TikTok untuk publish, bisa sekalian pilih sound trending). Setelah audit: Direct Post publik otomatis. |
| Posting Shorts | **YouTube Data API v3** `videos.insert` | Video: YouTube | Project belum terverifikasi → video privat sampai audit (estimasi 2–4 minggu). OAuth consent harus "In production" agar refresh token tidak kedaluwarsa 7 hari. |
| Render | FFmpeg + subtitle ASS (sudah dipakai) | — | ASS mampu: fade, reveal kata abu→putih, skala kata kunci, blur. **Remotion** hanya jika ASS terbukti kurang. |
| OpenCut | **Tidak dipakai** | — | README-nya: headless mode, Editor API, dan MCP masih "upcoming" di rewrite. Ditinjau ulang saat headless rilis. |
| MCP server | Tidak dibutuhkan saat runtime | — | Pipeline jalan di GitHub Actions; semua API dipanggil langsung dari Python. |

**Jam posting** (studi 2026): TikTok — sekitar 15:00 dan 20:00 waktu audiens paling sering disebut (Buffer 7,1 jt post; Sprout Social 2 M engagement; Metricool). Shorts — Jumat 16:00 dan malam hari kerja 18:00–21:00 (Buffer). Mulai dari slot D2, lalu sesuaikan dengan analytics akun sendiri setelah 2–3 minggu.

## Struktur Sheet1 baru (kompatibel dengan kolom lama A–F)

| Kol | Nama | Diisi oleh | Format |
|---|---|---|---|
| A | script | Spark | Narasi bahasa Inggris. Paragraf dipisah baris kosong = 1 adegan. `[pause]`, `[long pause]`, `*kata*` = penekanan |
| B | visuals | Spark | 1 baris per adegan (jumlah = jumlah paragraf A), kata kunci stok konkret, mis. `lone lion on rock black and white` |
| C | music_mood | Spark | `dark_epic` / `dark_reflective` / `soft_hopeful` / `soft_melancholic` |
| D | style | Spark | `dark_stoic` / `soft_healing` |
| E | video_url | Mesin | Link run GitHub Actions |
| F | status | Spark→Mesin | `READY` → `RENDERING` → `PREVIEW` → `APPROVED` → `POSTED` · `REJECTED` · `FAILED` |
| G | voice_direction | Spark | Catatan sutradara untuk narator |
| H | caption | Spark | Caption TikTok (≤150 karakter) |
| I | hashtags | Spark | 3–5 hashtag |
| J | yt_title | Spark | Judul Shorts (≤90 karakter, diakhiri `#shorts`) |
| K | trend_ref | Spark | Link video tren yang diadaptasi |
| L | scheduled_at | Mesin | ISO 8601 UTC |
| M | tiktok_id | Mesin | publish_id |
| N | youtube_id | Mesin | video id |
| O | error | Mesin | Pesan error terakhir |

## Patterns to Mirror

| Kategori | Sumber | Pola |
|---|---|---|
| Penamaan | `generator.py:41-80` | fungsi snake_case berbahasa Inggris, konstanta HURUF_BESAR di atas bagian terkait |
| Error | `generator.py:400-421` | sumber eksternal gagal → turun kualitas (fallback), render tidak berhenti |
| Logging | `generator.py:155`, `:404`, `:421` | `print("[*] ...")` proses, `[+]` sukses, `[!]` peringatan, bahasa Indonesia |
| Data | `generator.py:54-80` | Sheets via service account, range `Sheet1!A1:F50` |
| Tes | `tests/test_sequencing.py:1-29` | `unittest`, offline, `mock` untuk jaringan, butuh ffmpeg |

## Files to Change

| File | Aksi | Alasan |
|---|---|---|
| `generator.py` | UPDATE | Job parser baru, TTS Gemini + alignment, footage per adegan, caption kinetik 2 gaya, musik per mood |
| `scheduler.py` | CREATE | Tick: deteksi READY, proses tombol Telegram, posting di slot |
| `publish.py` | CREATE | Telegram, TikTok, YouTube (upload + refresh token) |
| `.github/workflows/pipeline.yml` | CREATE | cron `*/15` + manual; menjalankan scheduler lalu generator bila perlu |
| `.github/workflows/generate.yml` | DELETE | Digantikan pipeline.yml (tetap bisa manual lewat `workflow_dispatch`) |
| `assets/fonts/`, `assets/music/` | CREATE | Font OFL (Montserrat, Lora) + musik CC0/CC-BY dan `CREDITS.md` |
| `requirements.txt` | UPDATE | + `google-genai`; − `edge-tts`, `moviepy` bila tak terpakai |
| `tests/test_job_parsing.py`, `tests/test_captions.py`, `tests/test_scheduler.py` | CREATE | Tes offline |
| `docs/setup-telegram.md`, `docs/setup-tiktok.md`, `docs/setup-youtube.md`, `docs/gemini-spark-prompt.md` | CREATE | Panduan langkah demi langkah untuk user |
| `CLAUDE.md`, `ARCHITECTURE.md`, `PRD.md`, `MEMORY.md` | UPDATE | Selaraskan dengan v3 |

## Tasks

### Fase 0 — Spike (memverifikasi asumsi berisiko, sebelum membangun)
- **S1 TTS**: user membuat API key gratis di AI Studio (tanpa kartu). Render 1 naskah Dark + 1 Soft dengan Gemini TTS; ukur kata/menit dan porsi hening vs referensi (158–181 wpm saat bicara, 21–25% hening). Bandingkan dengan Kokoro. Catat kuota harian. **Validasi**: user mendengar 2 sampel dan memilih.
- **S2 TikTok**: user membuat app di TikTok for Developers (Login Kit + Content Posting API, scope `video.upload` + `video.publish`). Uji Upload to Inbox ke akun publik dari app belum diaudit. **Validasi**: draft muncul di inbox TikTok.
- **S3 Alignment**: whisper-timestamped pada audio Gemini — selisih waktu kata ≤ 0,15 dtk dari dengar manual.

### Fase 1 — Sheet & Spark
- Tulis header baru ke Sheet1 (A–O), finalkan `docs/gemini-spark-prompt.md`, user menempelkannya ke Spark.
- `fetch_ready_job()` mengembalikan dict semua kolom; validasi jumlah adegan A = baris B (jika beda → FAILED + pesan di O).
- **Validasi**: `tests/test_job_parsing.py`.

### Fase 2 — Narasi
- `generate_narration()` → Gemini TTS: suara per gaya (berat & tenang untuk Dark, hangat & lembut untuk Soft) + `voice_direction`; `[pause]`/`[long pause]` → tag jeda; `*kata*` → penekanan. Cadangan Kokoro, lalu edge-tts.
- Alignment → `word_timings`; normalisasi loudness narasi.
- **Validasi**: log menampilkan wpm & % hening; berada dalam rentang referensi ±15%.

### Fase 3 — Visual per adegan
- Durasi adegan = rentang waktu paragraf di narasi. Cari Pexels (video portrait dulu, lalu foto + Ken Burns), cadangan Pixabay, lalu pool Wikimedia.
- Grading: Dark = hitam-putih, kontras tinggi, vignette, zoom pelan; Soft = hangat, kontras lembut. Pemotongan adegan di batas kalimat.
- Atribusi Pexels ditambahkan ke deskripsi YouTube.
- **Validasi**: tes offline dengan mock API; satu render nyata per gaya.

### Fase 4 — Teks kinetik
- Dark: Montserrat ExtraBold kapital, kecil, tengah; kata muncul tepat saat diucapkan, kata berikutnya abu-abu → putih, `*kata*` diperbesar.
- Soft: Lora/serif, frasa utuh fade-in/out lembut.
- **Validasi**: `tests/test_captions.py` (timing & tag ASS); cek frame visual dibanding referensi.

### Fase 5 — Musik & mix
- Kurasi 4–5 trek per mood + `CREDITS.md`; pilih acak tanpa mengulang trek kemarin; ducking yang sudah ada; target loudness akhir −16 LUFS, LRA ≤ 5.
- **Validasi**: ebur128 di log.

### Fase 6 — Telegram
- User membuat bot via @BotFather (panduan di `docs/setup-telegram.md`); secret `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Kirim video + caption + hashtag + slot terjadwal; tombol ✅ Posting / 🔁 Render ulang / ❌ Batal. Mode `APPROVAL_MODE=manual|auto` (auto = posting tanpa menunggu tombol).
- **Validasi**: `tests/test_scheduler.py` (mock getUpdates) + uji nyata.

### Fase 7 — Posting
- TikTok: inbox draft (sebelum audit) / Direct Post (setelah audit). YouTube: `videos.insert` dengan judul J, deskripsi caption + atribusi, `#shorts`.
- Refresh token disimpan di tab Sheet `tokens` (hanya dibagikan ke service account dan user).
- Status POSTED + id; gagal → O + notifikasi Telegram.
- **Validasi**: posting nyata pertama di kedua platform.

### Fase 8 — Audit & penutup
- Halaman Privacy Policy/ToS (GitHub Pages), ajukan audit TikTok dan YouTube.
- Hapus dependensi tak terpakai, perbarui dokumen, hapus `generate.yml`.

## Validation

```bash
python3 -m unittest discover -s tests -v
gh workflow run pipeline.yml
gh run watch
```

## Risks

| Risiko | Kemungkinan | Mitigasi |
|---|---|---|
| Kuota gratis Gemini TTS terlalu kecil / berubah (preview) | Sedang | Spike S1; cadangan Kokoro di CPU; 1 video/hari cuma butuh beberapa request |
| Upload to Inbox TikTok juga diblokir untuk app belum diaudit | Sedang | Spike S2; cadangan: Telegram mengirim file, user unggah manual sampai audit lolos |
| Audit TikTok/YouTube ditolak atau lama | Sedang | Alur draft/privat tetap jalan; ajukan sejak Fase 8 dimulai |
| Akun Indonesia + konten Inggris: TikTok mendorong ke audiens lokal dulu | Sedang | Pantau analytics 2–3 minggu; sesuaikan slot/zona waktu |
| Footage stok tidak benar-benar "metafora" | Sedang | Spark menulis kata kunci konkret; urutan fallback; preview Telegram jadi gerbang kualitas |
| Lisensi musik/footage | Rendah | Hanya CC0/CC-BY/Pexels/Pixabay; `CREDITS.md`; atribusi di deskripsi |
| Cron GitHub telat 5–30 mnt atau mati setelah 60 hari tanpa aktivitas (repo publik) | Rendah | Slot posting toleran; workflow commit log bulanan sebagai keepalive |
| Refresh token TikTok/YouTube kedaluwarsa | Rendah | Disimpan & diperbarui otomatis di tab `tokens`; notifikasi Telegram saat gagal |

## Estimasi

| Fase | Perkiraan |
|---|---|
| 0 Spike | 0,5–1 hari (+ waktu user membuat akun developer) |
| 1–5 Mesin render | 3–4 hari |
| 6–7 Telegram & posting | 2 hari |
| 8 Audit & dokumen | 0,5 hari (+ 2–4 minggu menunggu audit) |

## Lampiran: draf prompt Gemini Spark

> Final disimpan di `docs/gemini-spark-prompt.md` setelah Fase 1. Diketik oleh user di Spark sebagai jadwal harian.

```
Jadwal: setiap hari pukul 08:00 WIB.

PERAN
Kamu adalah produser konten untuk akun TikTok & YouTube Shorts berbahasa Inggris bertema motivasi, stoik, dan healing.

LANGKAH 1 — RISET (wajib sebelum memberi ide)
- Cari 5–10 video yang sedang trending/FYP minggu ini di niche motivation, stoicism, discipline, healing, self-love (TikTok Creative Center, pencarian TikTok, YouTube Shorts).
- Untuk tiap video catat: link, hook 3 detik pertama, struktur kalimat, emosi, jenis visual, durasi, jumlah view/like.

LANGKAH 2 — TAWARKAN 3 IDE
Untuk tiap ide tulis: judul kerja, link video tren yang diadaptasi, apa yang ditiru dan apa yang disempurnakan, gaya (dark_stoic atau soft_healing), durasi (20–120 detik), hook kalimat pertama, dan 2–3 kalimat ringkasan isi.
Tunggu saya memilih (1/2/3) atau meminta revisi. Jangan menulis apa pun ke Sheet sebelum saya memilih.

LANGKAH 3 — TULIS KE SHEET (setelah saya memilih)
Tambahkan SATU baris baru di bawah baris terakhir pada Sheet1 spreadsheet "TikTok Automation Log". Jangan mengubah baris lain.
- A script: narasi bahasa Inggris. Jumlah kata ≈ durasi_detik × 2,3 (20 dtk ≈ 45 kata, 60 dtk ≈ 140, 120 dtk ≈ 275). Hook kuat di kalimat pertama. Kalimat pendek yang menghentak diselingi satu kalimat panjang. Pisahkan adegan dengan baris kosong (satu adegan 1–3 kalimat). Pakai [pause] untuk jeda singkat dan [long pause] sebelum kalimat puncak. Tandai 1–2 kata kunci per adegan dengan *bintang*.
- B visuals: satu baris per adegan, jumlah baris HARUS sama dengan jumlah adegan di A. Kata kunci stok footage bahasa Inggris yang konkret dan bisa difilmkan, metafora isi adegan (contoh: "lone lion standing on rock", "storm waves crashing at night", "woman silhouette at sunset beach"). Jangan kata abstrak seperti "hope" atau "success".
- C music_mood: dark_epic, dark_reflective, soft_hopeful, atau soft_melancholic.
- D style: dark_stoic (bangkit, disiplin, keras pada diri sendiri) atau soft_healing (lelah, patah hati, menerima diri).
- E: kosongkan.
- F status: READY
- G voice_direction: satu kalimat bahasa Inggris untuk narator (contoh: "Deep, weary male voice that slowly hardens into resolve; near-whisper on the first line, firm and loud on the last.").
- H caption: maksimal 150 karakter, bahasa Inggris, memancing komentar.
- I hashtags: 3–5 hashtag relevan dengan tren.
- J yt_title: maksimal 90 karakter, diakhiri #shorts.
- K trend_ref: link video tren yang diadaptasi.
- L sampai O: kosongkan.

ATURAN
- Jangan menyalin kalimat video tren kata per kata; adaptasi struktur dan emosinya.
- Tanpa nama merek, nama orang nyata, atau klaim medis.
- Setelah menulis, laporkan nomor baris yang kamu isi.
```
