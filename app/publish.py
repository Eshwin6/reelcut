"""Connect accounts and post through the official (free) APIs. No passwords are stored.

Instagram: "Instagram API with Instagram Login". Needs a Creator or Business account
(no Facebook Page needed) and a free Meta developer app (IG_APP_ID / IG_APP_SECRET).
Instagram downloads the reel from a public URL on this app.

TikTok: Content Posting API, direct post. Needs a free TikTok developer app
(TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET). Until TikTok audits the app, posts can
only be private (SELF_ONLY), which is the default for TIKTOK_PRIVACY.

Tokens are stored via storage.py and refreshed automatically before they expire.
"""
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

from . import storage

IG_GRAPH = "https://graph.instagram.com/v21.0"
TIKTOK = "https://open.tiktokapis.com/v2"
ACCOUNTS = "accounts.json"
_states = {}


def base_url():
    if os.environ.get("PUBLIC_BASE_URL"):
        return os.environ["PUBLIC_BASE_URL"].rstrip("/")
    if os.environ.get("SPACE_HOST"):  # set automatically on Hugging Face Spaces
        return "https://" + os.environ["SPACE_HOST"]
    return ""


def _req(method, url, data=None, headers=None, body=None):
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code}: {e.read().decode()[:500]}")
    return json.loads(raw) if raw else {}


def _accounts():
    return storage.read_json(ACCOUNTS, {})


def _save(platform, info):
    acc = _accounts()
    acc[platform] = info
    storage.write_json(ACCOUNTS, acc)


def disconnect(platform):
    acc = _accounts()
    acc.pop(platform, None)
    storage.write_json(ACCOUNTS, acc)


def status():
    acc = _accounts()
    return {
        "instagram": {"can_connect": bool(os.environ.get("IG_APP_ID") and base_url()),
                      "connected": "instagram" in acc, "name": acc.get("instagram", {}).get("username", "")},
        "tiktok": {"can_connect": bool(os.environ.get("TIKTOK_CLIENT_KEY") and base_url()),
                   "connected": "tiktok" in acc, "name": acc.get("tiktok", {}).get("username", "")},
    }


def connected():
    return [p for p, s in status().items() if s["connected"]]


# ---------- OAuth: Instagram ----------

def instagram_login_url():
    state = secrets.token_urlsafe(16)
    _states[state] = "instagram"
    return "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": os.environ["IG_APP_ID"], "redirect_uri": base_url() + "/auth/instagram/callback",
        "response_type": "code", "state": state,
        "scope": "instagram_business_basic,instagram_business_content_publish",
    })


def instagram_callback(code, state):
    if _states.pop(state, None) != "instagram":
        raise RuntimeError("Login expired, try again")
    short = _req("POST", "https://api.instagram.com/oauth/access_token", {
        "client_id": os.environ["IG_APP_ID"], "client_secret": os.environ["IG_APP_SECRET"],
        "grant_type": "authorization_code", "redirect_uri": base_url() + "/auth/instagram/callback",
        "code": code,
    })
    long = _req("GET", "https://graph.instagram.com/access_token?" + urllib.parse.urlencode({
        "grant_type": "ig_exchange_token", "client_secret": os.environ["IG_APP_SECRET"],
        "access_token": short["access_token"],
    }))
    token = long["access_token"]
    me = _req("GET", f"{IG_GRAPH}/me?fields=user_id,username&access_token={token}")
    _save("instagram", {"token": token, "user_id": str(me.get("user_id") or short.get("user_id")),
                        "username": me.get("username", ""),
                        "expires": time.time() + long.get("expires_in", 5184000)})


def _instagram_token():
    acc = _accounts().get("instagram")
    if not acc:
        raise RuntimeError("Instagram is not connected")
    if acc["expires"] - time.time() < 10 * 86400:  # long-lived tokens last 60 days; renew early
        r = _req("GET", "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token"
                        f"&access_token={acc['token']}")
        acc.update(token=r["access_token"], expires=time.time() + r.get("expires_in", 5184000))
        _save("instagram", acc)
    return acc


# ---------- OAuth: TikTok ----------

def tiktok_login_url():
    state = secrets.token_urlsafe(16)
    _states[state] = "tiktok"
    return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "response_type": "code", "state": state,
        "scope": "user.info.basic,video.publish", "redirect_uri": base_url() + "/auth/tiktok/callback",
    })


def _tiktok_token_request(fields):
    r = _req("POST", f"{TIKTOK}/oauth/token/", {
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        **fields,
    })
    if "access_token" not in r:
        raise RuntimeError(f"TikTok login failed: {r}")
    return {"token": r["access_token"], "refresh": r["refresh_token"], "open_id": r.get("open_id", ""),
            "expires": time.time() + r.get("expires_in", 86400)}


def tiktok_callback(code, state):
    if _states.pop(state, None) != "tiktok":
        raise RuntimeError("Login expired, try again")
    info = _tiktok_token_request({"code": code, "grant_type": "authorization_code",
                                  "redirect_uri": base_url() + "/auth/tiktok/callback"})
    try:
        me = _req("GET", f"{TIKTOK}/user/info/?fields=display_name",
                  headers={"Authorization": f"Bearer {info['token']}"})
        info["username"] = me.get("data", {}).get("user", {}).get("display_name", "")
    except RuntimeError:
        info["username"] = ""
    _save("tiktok", info)


def _tiktok_token():
    acc = _accounts().get("tiktok")
    if not acc:
        raise RuntimeError("TikTok is not connected")
    if acc["expires"] - time.time() < 600:  # access tokens last 24h; refresh tokens a year
        fresh = _tiktok_token_request({"grant_type": "refresh_token", "refresh_token": acc["refresh"]})
        acc.update(fresh)
        _save("tiktok", acc)
    return acc["token"]


# ---------- posting ----------

def post_instagram(video_url, caption):
    acc = _instagram_token()
    ig, token = acc["user_id"], acc["token"]
    c = _req("POST", f"{IG_GRAPH}/{ig}/media", {
        "media_type": "REELS", "video_url": video_url, "caption": caption,
        "share_to_feed": "true", "access_token": token,
    })
    cid = c["id"]
    for _ in range(90):  # Instagram processes the upload before it can be published
        s = _req("GET", f"{IG_GRAPH}/{cid}?fields=status_code,status&access_token={token}")
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram rejected the video: {s.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram processing timed out")
    p = _req("POST", f"{IG_GRAPH}/{ig}/media_publish", {"creation_id": cid, "access_token": token})
    return {"id": p.get("id")}


def post_tiktok(path, caption):
    token = _tiktok_token()
    size = os.path.getsize(path)
    chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
    count = max(1, size // chunk)
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    init = _req("POST", f"{TIKTOK}/post/publish/video/init/", headers=auth, body=json.dumps({
        "post_info": {
            "title": caption[:2200],
            "privacy_level": os.environ.get("TIKTOK_PRIVACY", "SELF_ONLY"),
            "disable_comment": False, "disable_duet": False, "disable_stitch": False,
        },
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk, "total_chunk_count": count},
    }).encode())
    if init.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok: {init['error']}")
    upload_url, publish_id = init["data"]["upload_url"], init["data"]["publish_id"]
    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size if i == count - 1 else start + chunk  # last chunk takes the remainder
            f.seek(start)
            data = f.read(end - start)
            _req("PUT", upload_url, body=data, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end - 1}/{size}",
            })
    for _ in range(60):
        s = _req("POST", f"{TIKTOK}/post/publish/status/fetch/", headers=auth,
                 body=json.dumps({"publish_id": publish_id}).encode())
        st = s.get("data", {}).get("status")
        if st == "PUBLISH_COMPLETE":
            return {"id": publish_id}
        if st == "FAILED":
            raise RuntimeError(f"TikTok publish failed: {s['data'].get('fail_reason')}")
        time.sleep(10)
    return {"id": publish_id, "note": "still processing on TikTok"}
