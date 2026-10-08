# MEMORY — Konteks Proyek yang Perlu Diingat

Catatan berumur panjang untuk manusia dan agen AI. Tambahkan entri baru di bagian paling atas tiap seksi; jangan hapus keputusan lama, tandai sebagai *digantikan*.

## Identitas

- Repo: https://github.com/marthen-wq/tiktok-video-engine (branch utama: `main`)
- Google Sheet antrean: ID `1wQepTnnoZi0rO5oPKkP5Qq8dfIcwqiAPg1r9_tadLf4`, tab `Sheet1`
- Pemilik berkomunikasi dalam Bahasa Indonesia. Komentar kode dan log berbahasa Indonesia; dokumen agen (`CLAUDE.md`, `AGENTS.md`) berbahasa Inggris.

## Keputusan

| Tanggal | Keputusan | Alasan |
|---|---|---|
| 2026-10-08 | Dokumen wajib sebelum pengembangan: PRD, ARCHITECTURE, ARCHITECTURE-ESSENTIALS, MEMORY, CLAUDE, AGENTS | Permintaan pemilik |
| 2026-10-08 | Background = 3–4 klip berbeda dengan crossfade 0,8 s (`plan_sequence`) | Video 30 detik harus terasa dinamis tapi halus |
| 2026-10-08 | Impor Google API dipindah ke dalam `get_sheets_service()` | Logika sequencing bisa diuji tanpa paket Google |
| 2026-10-08 | Subtitle disinkronkan lewat event `WordBoundary` edge-tts (bukan Whisper): tanpa PyTorch, tanpa install berat. Cadangan berlapis bila event tidak ada | Whisper menambah GB dependensi dan waktu run |
| 2026-10-08 | Ducking pakai `sidechaincompress`; `amix normalize=0`; narasi dual-mono lewat `pan` | `amix` default membagi dua level narasi; upmix mono→stereo biasa menurunkan 3 dB (terukur) |
| sebelumnya | Render serverless via GitHub Actions | Tanpa beban server fisik |
| sebelumnya | Suara `id-ID-ArdiNeural`, subtitle ASS 3 kata, BGM piano ambient | Gaya narator berwibawa, emas di tengah layar |

## Fakta yang sudah diverifikasi

- Pada 2026-10-08 `main` berisi `CLAUDE.md`, `generator.py`, `requirements.txt`, `.github/workflows/generate.yml`, `README.md`.
- 15 tes offline lulus (sequencing, sinkronisasi subtitle, ducking). Smoke render lengkap menghasilkan 1080x1920.
- Subtitle terbakar di video akhir sesuai event: muncul saat kata diucapkan, layar kosong di jeda panjang (diperiksa lewat frame).
- Ducking terukur: musik turun ~19 dB saat nada narasi aktif; level narasi masuk = keluar. Format event edge-tts 7.2.8 dibaca dari source (offset dalam tick 100 ns), tetapi tidak dijalankan terhadap layanan TTS nyata.
- Sandbox pengembangan memblokir Wikimedia dan Pixabay; unduhan nyata hanya bisa diuji di runner.
- Run Actions #2 (2026-10-08, commit `41c345c`): ketiga klip Wikimedia dan BGM Pixabay (2:27, stereo) terunduh; `WordBoundary (68 kata)`; install dependensi 2 menit (PyTorch + CUDA dari Whisper), render 4 menit 15 detik.
- Run yang sama menemukan bug: background hanya 10,7 s dari 33,9 s, sehingga video diam ~22 s. Unduhan terpotong 15 MB tetap membawa header durasi penuh (terbukti lokal: header 120 s, data 15,9 s). Pemicu persisnya tidak bisa direproduksi tanpa file asli; diperbaiki dengan remux, validasi panjang segmen, dan perpanjangan frame terakhir.
- Run #3 (`d2c7a26`): background 34,0 s dan frame berjalan sampai akhir, tetapi Wikimedia membalas **429 Too Many Requests** untuk keempat unduhan (User-Agent `Mozilla/5.0`), sehingga seluruh background warna polos. Jalur footage asli setelah perbaikan durasi belum teruji. Perbaikan: User-Agent deskriptif + retry sesuai `Retry-After`.
- Run #4 (`b9b8985`): 429 hilang. Akar masalah background pendek terungkap: file asli Commons berbitrate sangat tinggi, 15MB pertama hanya berisi 2,4 s (Rain) dan 0,9 s (Aberfeldy) gambar; Fog 10,1 s utuh. Durasi video benar (33,9 s) tetapi dua klip menjadi loop 0,9-2,4 s yang tersendat. Perbaikan: unduh versi transcode Wikimedia (`1080p.vp9.webm`, `720p.vp9.webm`, `720p.webm`) dulu, file asli sebagai cadangan.
- Run #5 (`e6ca750`): transcode 1080p VP9 terunduh untuk ketiga klip. Footage terpakai: Fog 10,1 s, Rain 5,9 s (klipnya memang hanya 5,9 s, jadi segmen 9 s berisi satu loop), Aberfeldy 24,8 s. Background 33,9 s, frame berjalan sampai akhir, output 17,9 MB. Pool 3 klip untuk 4 segmen: klip ke-4 memakai ulang Fog dari titik yang hampir sama dengan klip pertama.

## Hal yang belum benar (jangan diklaim sudah ada)

- Subtitle belum punya highlight kata per kata (`\k`); hanya tampilan 3 kata yang tersinkron.
- Level ducking baru diukur dengan nada uji, belum didengar dengan musik/suara asli.
- Whisper tercantum di dependensi tetapi tidak dipakai (sinkronisasi memakai edge-tts).
- Kolom B Sheet dan secret `OMNIROUTE_*` tidak dipakai kode.
- Kolom E Sheet berisi teks biasa; `DONE` ditulis sebelum artifact terunggah.

## Pertanyaan terbuka

1. Sumber footage jangka panjang: API Pexels (butuh `PEXELS_API_KEY`) agar pool lebih besar dan kolom B terpakai.
2. Lisensi klip dan BGM cukup untuk monetisasi?
3. Apa fungsi kolom C dan D di Sheet?
4. Perlu penjadwalan harian otomatis (cron)?

## Perintah yang sering dipakai

```bash
python3 -m unittest discover -s tests -v     # tes offline
QUOTE_INPUT="Teks uji" python3 generator.py  # jalankan lokal tanpa Sheet
```
