"""Distribusi: preview + tombol Telegram, posting TikTok & YouTube Shorts, unduh artifact video."""
import io
import json
import os
import zipfile

import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TIKTOK_CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
TIKTOK_MODE = (os.environ.get("TIKTOK_MODE") or "inbox").lower()        # inbox (draft) | direct (setelah audit)
TIKTOK_PRIVACY = os.environ.get("TIKTOK_PRIVACY") or "PUBLIC_TO_EVERYONE"
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_PRIVACY = os.environ.get("YOUTUBE_PRIVACY") or "public"

# ---------------------------------------------------------------- Telegram


def tg(method: str, **kw):
    if not TELEGRAM_BOT_TOKEN:
        return None
    r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", timeout=120, **kw)
    data = r.json()
    if not data.get("ok"):
        print(f"[!] Telegram {method} gagal: {data.get('description')}")
    return data.get("result")


def tg_message(text: str, buttons=None):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return tg("sendMessage", data=payload)


def tg_video(path: str, caption: str, buttons):
    with open(path, "rb") as f:
        return tg("sendVideo", files={"video": f}, data={
            "chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML",
            "supports_streaming": "true", "reply_markup": json.dumps({"inline_keyboard": buttons})})


def tg_updates(offset: int):
    return tg("getUpdates", data={"offset": offset, "timeout": 0,
                                  "allowed_updates": json.dumps(["callback_query"])}) or []


def tg_answer(callback_id: str, text: str):
    tg("answerCallbackQuery", data={"callback_query_id": callback_id, "text": text})


def tg_clear_buttons(chat_id, message_id):
    tg("editMessageReplyMarkup", data={"chat_id": chat_id, "message_id": message_id,
                                       "reply_markup": json.dumps({"inline_keyboard": []})})


def approval_buttons(row: int):
    return [[{"text": "✅ Posting", "callback_data": f"ok:{row}"},
             {"text": "🔁 Render ulang", "callback_data": f"redo:{row}"},
             {"text": "❌ Batal", "callback_data": f"no:{row}"}]]

# ---------------------------------------------------------------- Artifact GitHub


def download_artifact(name: str, dest_dir: str) -> bool:
    """Ambil artifact terbaru bernama `name` dari repo ini (butuh GITHUB_TOKEN dengan actions: read)."""
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return False
    auth = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"https://api.github.com/repos/{repo}/actions/artifacts", headers=auth,
                     params={"name": name, "per_page": 5}, timeout=30)
    arts = [a for a in r.json().get("artifacts", []) if not a.get("expired")]
    if not arts:
        return False
    z = requests.get(arts[0]["archive_download_url"], headers=auth, timeout=600)
    zipfile.ZipFile(io.BytesIO(z.content)).extractall(dest_dir)
    return True

# ---------------------------------------------------------------- TikTok

TIKTOK_API = "https://open.tiktokapis.com/v2"
SINGLE_CHUNK_MAX = 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024


def tiktok_access_token(refresh_token: str):
    """Tukar refresh token -> (access token, refresh token terbaru). TikTok bisa merotasi refresh token."""
    r = requests.post(f"{TIKTOK_API}/oauth/token/", timeout=30, data={
        "client_key": TIKTOK_CLIENT_KEY, "client_secret": TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token", "refresh_token": refresh_token})
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError(f"refresh token TikTok ditolak: {d.get('error_description') or d}")
    return d["access_token"], d.get("refresh_token") or refresh_token


def chunk_plan(size: int):
    """(chunk_size, total_chunk_count) sesuai aturan TikTok: <=64MB satu chunk, selebihnya 10MB + sisa di chunk akhir."""
    if size <= SINGLE_CHUNK_MAX:
        return size, 1
    return CHUNK, size // CHUNK


def tiktok_upload(video: str, access_token: str, title: str) -> str:
    """Unggah video. Mode inbox: masuk draft (notifikasi di app TikTok). Mode direct: langsung terbit."""
    size = os.path.getsize(video)
    chunk, count = chunk_plan(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}
    if TIKTOK_MODE == "direct":
        url = f"{TIKTOK_API}/post/publish/video/init/"
        body = {"post_info": {"title": title[:2200], "privacy_level": TIKTOK_PRIVACY, "disable_comment": False,
                              "disable_duet": False, "disable_stitch": False, "video_cover_timestamp_ms": 1000},
                "source_info": source}
    else:
        url = f"{TIKTOK_API}/post/publish/inbox/video/init/"
        body = {"source_info": source}
    r = requests.post(url, json=body, timeout=60, headers={
        "Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"})
    d = r.json()
    if d.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"init TikTok gagal: {d.get('error')}")
    upload_url, publish_id = d["data"]["upload_url"], d["data"]["publish_id"]
    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            data = f.read(end - start + 1)
            put = requests.put(upload_url, data=data, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if put.status_code not in (200, 201, 206):
                raise RuntimeError(f"unggah chunk TikTok {i + 1}/{count} gagal: HTTP {put.status_code}")
    return publish_id

# ---------------------------------------------------------------- YouTube


def youtube_upload(video: str, title: str, description: str, tags) -> str:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=YOUTUBE_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token",
                        client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET,
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {"snippet": {"title": title[:100], "description": description[:5000], "tags": list(tags)[:15],
                        "categoryId": "22"},
            "status": {"privacyStatus": YOUTUBE_PRIVACY, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(video, mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def configured(tiktok_refresh: str):
    return {
        "tiktok": bool(TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET and tiktok_refresh),
        "youtube": bool(YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN),
    }
