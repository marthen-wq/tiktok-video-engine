# Panduan setup v3

Semua langkah di bawah gratis. Kredensial selalu kamu pasang sendiri lewat `gh secret set` (diketik/ditempel di terminal, tidak pernah ditulis ke file repo).

Status yang sudah terpasang bisa dicek dengan:

```bash
gh secret list
```

## 1. Footage: Pexels (wajib) dan Pixabay (opsional)

1. Daftar di <https://www.pexels.com/api/> → **Your API Key**.
2. `gh secret set PEXELS_API_KEY`
3. Opsional, cadangan footage: daftar di <https://pixabay.com/api/docs/> → `gh secret set PIXABAY_API_KEY`

## 2. Telegram: preview dan tombol persetujuan

1. Telegram → **@BotFather** → `/newbot` → nama bebas, username diakhiri `bot`.
2. Salin token → `gh secret set TELEGRAM_BOT_TOKEN`
3. Buka bot barumu, kirim `/start` (bot memang tidak membalas).
4. Buka **@userinfobot** → salin angka **Id** → `gh secret set TELEGRAM_CHAT_ID`

Hanya chat dengan ID ini yang bisa menekan tombol. Tombol orang lain ditolak.

### Cara memakai di Telegram

Setiap video selesai dirender, bot mengirim:

- video preview (720p) + caption + hashtag + judul Shorts + jadwal tayang bila disetujui;
- tombol **✅ Posting** (dijadwalkan ke slot berikutnya), **🔁 Render ulang** (dirender ulang ±15 menit lagi), **❌ Batal**.

Bot menanggapi tombol dalam ≤15 menit (dicek oleh cron). Setelah tayang, bot mengirim link YouTube dan status TikTok.

## 3. TikTok

1. Buka <https://developers.tiktok.com/> → login dengan akun TikTok-mu → **Manage apps → Connect an app**.
2. Isi profil app:
   - **Website URL**: `https://marthen-wq.github.io/tiktok-video-engine/`
   - **Terms of Service URL**: `https://marthen-wq.github.io/tiktok-video-engine/terms.html`
   - **Privacy Policy URL**: `https://marthen-wq.github.io/tiktok-video-engine/privacy.html`
   - Platform: **Web**
3. **Add products**: **Login Kit** dan **Content Posting API** (aktifkan *Direct Post*).
   - Login Kit → **Redirect URI**: `https://marthen-wq.github.io/tiktok-video-engine/tiktok-callback.html`
   - Scopes: `user.info.basic`, `video.upload`, `video.publish`
4. Buat **Sandbox** → tambahkan akun TikTok-mu sebagai **Target user** (bisa dipakai tanpa menunggu review).
5. Di laptop, dari folder project:
   ```bash
   python3 auth_setup.py tiktok
   ```
   Masukkan Client Key dan Client Secret (dari halaman app/sandbox), login di browser, salin kode dari halaman yang muncul, tempel ke terminal. Skrip menyimpan `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN` langsung ke GitHub Secrets.

**Sebelum audit**: video masuk sebagai **draft di inbox TikTok** (mode `inbox`). Buka notifikasi TikTok → tempel caption dari Telegram → pilih sound bila mau → **Post**.

**Setelah audit lolos** (ajukan dari halaman app: *Content Posting API → Apply for audit*): ubah ke posting otomatis penuh:

```bash
gh variable set TIKTOK_MODE --body direct
```

## 4. YouTube Shorts

1. <https://console.cloud.google.com/> → pilih project `tiktok-automation-bot-510913`.
2. **APIs & Services → Library** → aktifkan **YouTube Data API v3**.
3. **OAuth consent screen** → User type **External** → isi nama app & email → **Publish app** (status *In production*; tanpa ini token kedaluwarsa tiap 7 hari).
4. **Credentials → Create credentials → OAuth client ID → Desktop app** → **Download JSON**.
5. Di laptop:
   ```bash
   pip3 install google-auth-oauthlib requests
   ```
   ```bash
   python3 auth_setup.py youtube ~/Downloads/client_secret_XXXX.json
   ```
   Browser terbuka → pilih channel → muncul "Google hasn't verified this app" → **Advanced → Go to app** → Allow. Skrip menyimpan `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.
6. Hapus file JSON dari Downloads.

**Sebelum audit**: video terunggah sebagai **privat**; ubah ke publik di YouTube Studio. Ajukan audit lewat formulir *YouTube API Services – Audit and Quota Extension* (estimasi 2–4 minggu).

## 5. Pengaturan (tanpa rahasia)

| Variabel | Default | Arti |
|---|---|---|
| `APPROVAL_MODE` | `manual` | `auto` = video langsung dijadwalkan tanpa menunggu tombol ✅ |
| `TIKTOK_MODE` | `inbox` | `direct` setelah audit TikTok lolos |
| `POST_SLOTS` | `15:00,20:00` | Jam tayang dalam zona audiens |
| `AUDIENCE_TZ` | `America/New_York` | Zona waktu audiens (DST otomatis) |

Contoh: `gh variable set APPROVAL_MODE --body auto`

## 6. Gemini Spark

Tempel prompt di [gemini-spark-prompt.md](gemini-spark-prompt.md) sebagai tugas harian 08:00 WIB.

## Alur harian setelah semua terpasang

1. 08:00 WIB Spark mengirim 3 ide → kamu pilih.
2. Spark menulis baris `READY` → dalam ±15 menit pipeline merender (±5–10 menit).
3. Telegram: preview masuk → tekan ✅.
4. Pada slot berikutnya (02:00 atau 07:00 WIB selama musim panas AS) video tayang; Telegram mengirim konfirmasi.

Menjalankan pipeline manual: `gh workflow run pipeline.yml` (atau `-f row=12` untuk memaksa render baris 12).
