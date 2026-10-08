# PRD — TikTok Shorts Video Engine

Status dokumen: v1.0 · Basis kode: `generator.py` v2.0 + sequencing multi-klip (v2.1)

## 1. Ringkasan

Mesin otomatis yang mengubah baris antrean teks motivasi di Google Sheets menjadi video vertikal 9:16 (1080x1920) siap unggah ke TikTok / YouTube Shorts. Seluruh render berjalan serverless di GitHub Actions, sehingga tidak ada server fisik yang perlu dirawat.

## 2. Masalah dan tujuan

**Masalah.** Membuat video motivasi harian secara manual (cari footage, rekam suara, pasang subtitle, mix musik) memakan 30–60 menit per video dan sulit dijaga konsistensinya.

**Tujuan.**
1. Satu baris `READY` di Sheet menghasilkan satu MP4 tanpa campur tangan manual.
2. Gaya visual dan audio konsisten: narator berwibawa, subtitle tebal emas di tengah layar, footage sinematik, musik piano ambient.
3. Biaya operasional nol rupiah di luar kuota GitHub Actions gratis.

**Bukan tujuan (saat ini).** Mengunggah otomatis ke TikTok, editor video interaktif, banyak bahasa, thumbnail, analitik performa.

## 3. Pengguna

| Persona | Kebutuhan |
|---|---|
| Kreator konten (pemilik repo) | Mengisi kalimat motivasi di Sheet, menerima video jadi, mengunggah sendiri |
| Maintainer / agen AI | Memahami arsitektur cepat, memperbaiki bug, menambah fitur tanpa merusak pipeline |

## 4. Alur pengguna

1. Kreator mengisi baris baru di Google Sheets (kolom A = kalimat, B = tema visual) dan menandai kolom F = `READY`.
2. Workflow dipicu manual (`workflow_dispatch`) atau lewat `repository_dispatch` (`generate-video`).
3. Mesin mengambil baris `READY` pertama, merender video, mengunggahnya sebagai GitHub Artifact (retensi 7 hari).
4. Sheet diperbarui: kolom E = referensi artifact, kolom F = `DONE`.
5. Kreator mengunduh MP4 dari halaman run Actions dan mengunggahnya ke platform.

Jalur alternatif: `quote_override` pada `workflow_dispatch` melewati Sheet sama sekali (berguna untuk uji coba; Sheet tidak diubah).

## 5. Kebutuhan fungsional

| ID | Kebutuhan | Prioritas | Status |
|---|---|---|---|
| F1 | Baca antrean dari Sheet, ambil baris `READY` pertama | P0 | Ada |
| F2 | Voiceover Indonesia via edge-tts `id-ID-ArdiNeural` (rate -5%, pitch -3Hz) | P0 | Ada |
| F3 | Subtitle ASS, 3 kata per baris, huruf kapital tebal kuning/emas, tengah layar | P0 | Ada (tersinkron ucapan, lihat F8) |
| F4 | Background 3–4 klip berbeda dengan crossfade halus, 1080x1920, 30 fps | P0 | Ada (v2.1), diuji dengan klip sintetis |
| F5 | Musik latar piano ambient dicampur di bawah narasi | P0 | Ada (dengan ducking, lihat F9) |
| F6 | Simpan MP4 sebagai Artifact, set status `DONE` | P0 | Ada (kolom E hanya teks, bukan tautan) |
| F7 | Fallback otomatis saat footage / BGM gagal diunduh | P1 | Ada |
| F8 | Subtitle tersinkron dengan ucapan sebenarnya | P1 | Ada: event WordBoundary edge-tts, cadangan SentenceBoundary lalu proporsional panjang kata. Belum teruji dengan suara asli |
| F9 | Ducking sungguhan (musik turun saat narator bicara) | P1 | Ada: `sidechaincompress`, turun ~19 dB pada nada uji. Nilai akhir perlu disetel dengan telinga |
| F10 | Footage mengikuti kolom B (tema) | P2 | Belum (kolom dibaca tapi tidak dipakai) |
| F11 | Tulis tautan Artifact yang bisa diklik ke Sheet | P2 | Belum |

## 6. Kebutuhan non-fungsional

- **Durasi run:** di bawah 15 menit (batas `timeout-minutes` workflow).
- **Keandalan:** kegagalan sumber eksternal (footage, BGM) tidak boleh menggagalkan render; hasil turun kualitas, bukan berhenti.
- **Keamanan:** kredensial hanya di GitHub Secrets; Sheet hanya dibagikan ke service account.
- **Biaya:** hanya memakai layanan gratis.
- **Kepatuhan lisensi:** footage dan musik harus boleh dipakai untuk konten monetisasi (lihat risiko).

## 7. Metrik keberhasilan

- Tingkat sukses run ≥ 95% (run hijau dengan MP4 valid).
- Waktu dari `READY` ke MP4 ≤ 10 menit.
- Setiap video 30 detik berisi 3–4 klip berbeda tanpa lompatan kasar (diverifikasi oleh `tests/test_sequencing.py`).
- Nol intervensi manual per video selain unggah.

## 8. Risiko dan asumsi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Footage Wikimedia terunduh di runner (run #2), tetapi Wikimedia meminta User-Agent deskriptif dan bisa membatasi hotlink; unduhan terpotong 15 MB membawa header durasi palsu | Klip jatuh ke warna polos, atau background terlalu pendek (terjadi di run #2) | Remux + validasi segmen + perpanjangan frame (sudah); jangka panjang: API stok berlisensi jelas (mis. Pexels) |
| Lisensi klip Wikimedia beragam (atribusi / share-alike) | Masalah klaim hak cipta | Audit lisensi tiap klip sebelum monetisasi |
| URL BGM Pixabay bersifat CDN sementara | BGM jatuh ke nada sinus | Simpan BGM berlisensi jelas di `assets/` |
| edge-tts adalah layanan tidak resmi | Bisa berubah / dibatasi | Pin versi; siapkan TTS cadangan |
| Dependensi berat di `requirements.txt` (`whisper-timestamped` menarik PyTorch) | Install lambat, mendekati batas 15 menit | Hapus dependensi yang tidak dipakai (F8 kini memakai edge-tts, bukan Whisper) |
| Status `DONE` ditulis sebelum langkah upload artifact selesai | Baris tercatat selesai padahal artifact gagal | Pindahkan update Sheet ke langkah setelah upload |

Asumsi: Sheet bernama `Sheet1`, kolom A–F seperti di ARCHITECTURE.md, dan service account sudah diberi akses edit.

## 9. Roadmap

- **P0 — Validasi:** jalankan workflow nyata, periksa log unduhan footage/BGM, tonton hasilnya.
- **P1 — Kualitas:** setel level ducking dengan telinga, highlight kata per kata (`\k`) bila diinginkan.
- **P2 — Otomasi:** footage sesuai tema, tautan Artifact di Sheet, penjadwalan harian.
