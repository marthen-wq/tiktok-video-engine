# TikTok Shorts Video Engine 🎬 (Architecture & Development Guide)

This repository automates the production of high-converting, professional TikTok / YouTube Shorts motivational videos using **GitHub Actions (Serverless Rendering)**, **Google Sheets**, and **Edge-TTS / Whisper AI**.

## 🏗️ Architecture Overview

```
Google Sheets (Queue: status = READY)
        ↓
GitHub Actions (Workflow: generate.yml)
        ↓
generator.py
  ├── 1. Fetch quote & environment from Google Sheets
  ├── 2. Generate Voiceover TTS via edge-tts (id-ID-ArdiNeural, deep stoic pacing)
  ├── 3. Dynamic Karaoke Subtitles via ASS format (word/phrase-by-phrase centered, bold yellow typography)
  ├── 4. Stock Footage Download (HD vertical 9:16 clips from Wikimedia Commons / direct streams)
  ├── 5. Background Music (Piano ambient with automatic audio ducking)
  ├── 6. FFmpeg compositing & rendering
        ↓
Output: MP4 Video (1080x1920) stored in GitHub Artifacts
        ↓
Update Google Sheets: status = DONE, video_url = GitHub Artifact link
```

## 📁 Repository Structure
- `.github/workflows/generate.yml`: Workflow trigger (`repository_dispatch` and `workflow_dispatch`).
- `generator.py`: Core video generation engine.
- `requirements.txt`: Python dependencies (`edge-tts`, `whisper-timestamped`, `google-api-python-client`, etc.).
- `README.md`: Overview documentation.

## 🔐 Required Secrets (Settings → Secrets and variables → Actions)
- `SPREADSHEET_ID`: Target Google Sheets document ID (`1wQepTnnoZi0rO5oPKkP5Qq8dfIcwqiAPg1r9_tadLf4`).
- `GCP_SERVICE_ACCOUNT_KEY`: Service account JSON credential with Google Sheets API access.
- `OMNIROUTE_URL`: LLM gateway endpoint for script/hook generation.
- `OMNIROUTE_KEY`: LLM gateway authorization key.

## 🚀 How to Run & Test
1. Set a row in Google Sheets with `status = READY`.
2. Trigger the GitHub Action manually:
   - Go to **Actions** → **Auto TikTok Shorts Video Generator** → **Run workflow**.
3. Download the finished MP4 video from the **Artifacts** section at the bottom of the run summary.
