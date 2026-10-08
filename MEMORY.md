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
- Sandbox pengembangan memblokir Wikimedia dan Pixabay, jadi unduhan nyata **belum pernah teruji** di sana.

## Hal yang belum benar (jangan diklaim sudah ada)

- Subtitle belum punya highlight kata per kata (`\k`); hanya tampilan 3 kata yang tersinkron.
- Level ducking baru diukur dengan nada uji, belum didengar dengan musik/suara asli.
- Whisper tercantum di dependensi tetapi tidak dipakai (sinkronisasi memakai edge-tts).
- Kolom B Sheet dan secret `OMNIROUTE_*` tidak dipakai kode.
- Kolom E Sheet berisi teks biasa; `DONE` ditulis sebelum artifact terunggah.

## Pertanyaan terbuka

0. Apakah `id-ID-ArdiNeural` mengirim `WordBoundary`? Log run pertama akan menampilkan `Sinkronisasi subtitle: WordBoundary (N kata)` atau peringatan cadangan.

1. Apakah URL footage Wikimedia terunduh dari runner GitHub? (cek log run pertama)
2. Lisensi klip dan BGM cukup untuk monetisasi?
3. Apa fungsi kolom C dan D di Sheet?
4. Perlu penjadwalan harian otomatis (cron)?

## Perintah yang sering dipakai

```bash
python3 -m unittest discover -s tests -v     # tes offline
QUOTE_INPUT="Teks uji" python3 generator.py  # jalankan lokal tanpa Sheet
```
