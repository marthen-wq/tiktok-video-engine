# ARCHITECTURE-ESSENTIALS

Ringkasan cepat. Detail lengkap: [ARCHITECTURE.md](ARCHITECTURE.md).

## Alur

`Google Sheet (F=READY)` → `GitHub Actions` → `generator.py` → `MP4 1080x1920 (Artifact)` → `Sheet F=DONE`

Pipeline `generator.py` (serial): ambil quote → TTS → durasi (ffprobe) → subtitle ASS → BGM → background multi-klip → render → update Sheet.

## Keputusan kritis

1. **Serverless di GitHub Actions.** Tidak ada server. Batas run 15 menit.
2. **Google Sheet = antrean + status.** Tanpa database. Kolom: A quote, B tema, E hasil, F status.
3. **FFmpeg untuk semua media.** Scale/crop, xfade, subtitle (libass), mix audio, encode.
4. **edge-tts `id-ID-ArdiNeural`** untuk suara. Gratis, tidak resmi.
5. **Subtitle ASS**, 3 kata per baris, tengah layar, font DejaVu Sans Bold. Waktu dari event `WordBoundary` edge-tts; cadangan: `SentenceBoundary`, lalu proporsional panjang kata.
6. **Ducking nyata:** `sidechaincompress` (narasi mengendalikan musik) + `amix normalize=0`. Level = konstanta `BGM_VOLUME`, `DUCK_*`.
7. **Background 3–4 klip + crossfade 0,8 s.** `n = clamp(ceil(total/9), 3, 4)`; panjang hasil tepat `total`.
8. **Degradasi, bukan gagal.** Footage/BGM gagal → fallback (warna polos / nada sinus), render tetap jalan.
9. **Rahasia hanya di GitHub Secrets.** Jangan commit kredensial.

## Kontrak penting

- Output: `output/shorts_<row|motivasi>.mp4`, H.264 + AAC, 1080x1920, 30 fps.
- Durasi video = durasi narasi + ~1,2–1,5 s.
- `QUOTE_INPUT` mengabaikan Sheet dan tidak mengubah status.

## Celah terbuka (jangan diasumsikan sudah ada)

- Level ducking belum disetel dengan telinga; `WordBoundary` untuk `id-ID-ArdiNeural` belum terverifikasi.
- Footage sesuai kolom B.
- Tautan Artifact di Sheet; `DONE` ditulis sebelum upload.
- URL footage/BGM belum terverifikasi dari runner.

## Tes

`python3 -m unittest discover -s tests -v` (offline, butuh ffmpeg). Uji nyata: jalankan workflow dari tab Actions.
