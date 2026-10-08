# TikTok Shorts Video Engine 🎬 (Architecture & Development Guide)

Automates motivational TikTok / YouTube Shorts videos (1080x1920) using **GitHub Actions (serverless rendering)**, **Google Sheets** as the queue, **edge-tts** for voiceover and **FFmpeg** for compositing.

Read order for new contributors: this file → `ARCHITECTURE-ESSENTIALS.md` → `ARCHITECTURE.md` (full) → `PRD.md` (scope, roadmap) → `MEMORY.md` (decisions, verified facts). Agent rules: `AGENTS.md`.

## 🏗️ Architecture Overview

```
Google Sheets (Queue: column F status = READY)
        ↓
GitHub Actions (generate.yml)
        ↓
generator.py  main()
  ├── 1. fetch_ready_quote()         first READY row → quote (A), environment (B)
  ├── 2. generate_narration()        edge-tts id-ID-ArdiNeural (rate -5%, pitch -3Hz)
  ├── 3. create_ass_subtitles()      ASS, 3 words per line, bold yellow, centered, timed from TTS word events
  ├── 4. prepare_bgm()               piano ambient (fallback: 110 Hz sine drone)
  ├── 5. prepare_background_video()  3–4 different clips + crossfade (see below)
  ├── 6. render_shorts_video()       burn subtitles, mix narration + BGM with sidechain ducking, H.264/AAC
  └── 7. update_sheet_status()       column E reference, column F = DONE
        ↓
Output: output/shorts_<row|motivasi>.mp4 → GitHub Artifact (7 days)
```

### Multi-clip sequencing (v2.1)
`plan_sequence(total)`: `n = clamp(ceil(total/9), 3, 4)` clips, crossfade `min(0.8, total/(3n))`, output length equals `total` exactly. Clips are chosen by `pick_clip_urls` (no two identical clips in a row), cut from a random start by `make_segment`, failed downloads become a flat-colour segment (`make_fallback_segment`), and `crossfade_segments` chains them with `xfade` (fade → dissolve → fadeblack). A 30 s narration gives 4 clips of ~8.5 s.

## 📁 Repository Structure
- `.github/workflows/generate.yml`: workflow (`repository_dispatch: generate-video` and `workflow_dispatch` with `quote_override`).
- `generator.py`: the whole engine.
- `tests/test_sequencing.py`, `tests/test_audio_subtitles.py`: offline tests (need `ffmpeg`).
- `requirements.txt`: Python dependencies.
- `PRD.md`, `ARCHITECTURE.md`, `ARCHITECTURE-ESSENTIALS.md`, `MEMORY.md`, `AGENTS.md`: project docs.

## 🔐 Required Secrets (Settings → Secrets and variables → Actions)
- `SPREADSHEET_ID`: Google Sheet ID (`1wQepTnnoZi0rO5oPKkP5Qq8dfIcwqiAPg1r9_tadLf4`).
- `GCP_SERVICE_ACCOUNT_KEY`: service account JSON; the Sheet must be shared with its email as Editor.
- `OMNIROUTE_URL`, `OMNIROUTE_KEY`: LLM gateway. Passed to the job but **not used by the code yet**.

Never commit credentials.

## ✅ What is real vs. not yet (do not claim otherwise)
- Ducking is real (`sidechaincompress` keyed by the narration, `amix normalize=0`), but the levels (`BGM_VOLUME`, `DUCK_*`) were only measured with test tones — tune by ear.
- Subtitle timing comes from edge-tts `WordBoundary` events (fallbacks: `SentenceBoundary`, then length-proportional). `id-ID-ArdiNeural` does emit word events (verified on the runner, 68 words); the run log says which source was used. There are no per-word `\k` highlights. `whisper-timestamped` is in `requirements.txt` but unused.
- Sheet column B (environment) is read but does not influence footage.
- Column E stores plain text, and `DONE` is written before the artifact upload step.
- Footage (all 3 Wikimedia URLs) and the Pixabay BGM downloaded fine on the runner (run 2, 2026-10-08). That run exposed a short-background bug (10.7 s of 33.9 s); it is guarded by remux + segment-length checks + a final pad, Run 3 confirmed the length guard (34.0 s, frames to the end) but Wikimedia answered 429 to all downloads with the generic `Mozilla/5.0` UA, so every clip was a flat-colour fallback. Downloads now use a descriptive `USER_AGENT` and retry on 429/503; run 4 had no 429. Run 4 also showed that the 4K originals give only 0.9–2.4 s of picture per 15 MB, so downloads now prefer Wikimedia's 1080p/720p transcodes (`footage_candidates`); not yet verified on the runner.
- `requirements.txt` pulls PyTorch + CUDA via `whisper-timestamped` (install step ~2 min).

## 🚀 How to Run & Test

**Offline tests (no network, no credentials):**
```bash
python3 -m unittest discover -s tests -v    # ~50 s, 15 tests, needs ffmpeg + requests
```

**Local run without Sheets** (needs `pip install -r requirements.txt` or at least `edge-tts requests`, plus `ffmpeg`):
```bash
QUOTE_INPUT="Kamu tidak sedang tertinggal, kamu sedang ditempa." python3 generator.py
# result: output/shorts_motivasi.mp4
```

**On GitHub Actions:**
1. Smoke test without the Sheet: **Actions → Auto TikTok Shorts Video Generator → Run workflow**, fill `quote_override` with a ~30 s text (about 70–80 words).
2. In the run log check: `Sinkronisasi subtitle: WordBoundary (N kata)` (a `[!] Tidak ada event batas` line means the fallback was used), `Menyusun 4 klip`, one `[+] Klip ... valid` line per clip (a `[!] Gagal mengunduh` line means that clip fell back to a flat colour), and `Background multi-klip siap`.
3. Download `tiktok-shorts-video` from Artifacts and watch it: 3–4 scene changes, smooth fades, gold subtitles centered, narration clearly louder than music, music rising in pauses and dipping while the narrator speaks, subtitles appearing as each word group is spoken.
4. Full test: set one Sheet row to `READY`, run with `quote_override` empty, confirm F becomes `DONE`.
