#!/usr/bin/env python3
"""Sekali jalan di laptop: hubungkan TikTok / YouTube lalu simpan token langsung ke GitHub Secrets.

  python3 auth_setup.py tiktok
  python3 auth_setup.py youtube path/ke/client_secret.json      (butuh: pip install google-auth-oauthlib)

Token tidak pernah dicetak ke layar; skrip menyimpannya lewat `gh secret set`.
"""
import getpass
import secrets
import subprocess
import sys
import urllib.parse
import webbrowser

import requests

REPO = "marthen-wq/tiktok-video-engine"
TIKTOK_REDIRECT = "https://marthen-wq.github.io/tiktok-video-engine/tiktok-callback.html"
TIKTOK_SCOPES = "user.info.basic,video.upload,video.publish"


def set_secret(name: str, value: str):
    subprocess.run(["gh", "secret", "set", name, "-R", REPO], input=value, text=True, check=True)


def tiktok():
    key = input("TikTok Client Key: ").strip()
    secret = getpass.getpass("TikTok Client Secret (tidak terlihat saat diketik): ").strip()
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": key, "scope": TIKTOK_SCOPES, "response_type": "code",
        "redirect_uri": TIKTOK_REDIRECT, "state": secrets.token_urlsafe(8)})
    print("\nBrowser akan terbuka. Login ke TikTok, klik Authorize, lalu salin kode yang muncul.\n" + url)
    webbrowser.open(url)
    code = urllib.parse.unquote(input("\nTempel kode di sini: ").strip())
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
        "client_key": key, "client_secret": secret, "code": code,
        "grant_type": "authorization_code", "redirect_uri": TIKTOK_REDIRECT})
    d = r.json()
    if "refresh_token" not in d:
        sys.exit(f"Gagal menukar kode: {d.get('error_description') or d}")
    for name, value in [("TIKTOK_CLIENT_KEY", key), ("TIKTOK_CLIENT_SECRET", secret),
                        ("TIKTOK_REFRESH_TOKEN", d["refresh_token"])]:
        set_secret(name, value)
    print(f"✓ TikTok terhubung (scope: {d.get('scope')}). Tiga secret tersimpan di {REPO}.")


def youtube(client_file: str):
    import json
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(client_file, ["https://www.googleapis.com/auth/youtube.upload"])
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    info = json.load(open(client_file))["installed"]
    for name, value in [("YOUTUBE_CLIENT_ID", info["client_id"]), ("YOUTUBE_CLIENT_SECRET", info["client_secret"]),
                        ("YOUTUBE_REFRESH_TOKEN", creds.refresh_token)]:
        set_secret(name, value)
    print(f"✓ YouTube terhubung. Tiga secret tersimpan di {REPO}.")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "tiktok":
        tiktok()
    elif len(sys.argv) >= 3 and sys.argv[1] == "youtube":
        youtube(sys.argv[2])
    else:
        sys.exit(__doc__)
