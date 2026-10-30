"""ReelCut server: phone uploads footage, a worker edits it, then it posts."""
import hashlib
import hmac
import json
import os
import queue
import secrets
import shutil
import threading
import time
import traceback
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from . import pipeline, publish, storage

DATA = storage.DATA
JOBS = os.path.join(DATA, "jobs")
PASSWORD = os.environ.get("APP_PASSWORD", "")
STATIC = os.path.join(os.path.dirname(__file__), "static")
KEEP_DAYS = float(os.environ.get("KEEP_DAYS", "3"))  # edited videos are deleted after this
os.makedirs(JOBS, exist_ok=True)

app = FastAPI()
work = queue.Queue()
lock = threading.Lock()


# ---------- storage ----------

def _job_path(jid):
    if not jid.isalnum():
        raise HTTPException(404)
    return os.path.join(JOBS, jid)


def load_job(jid):
    try:
        with open(os.path.join(_job_path(jid), "job.json")) as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(404)


def save_job(job):
    with lock:
        p = os.path.join(_job_path(job["id"]), "job.json")
        with open(p + ".tmp", "w") as f:
            json.dump(job, f)
        os.replace(p + ".tmp", p)


def update_job(jid, **kw):
    job = load_job(jid)
    job.update(kw)
    save_job(job)
    return job


def load_brands():
    return storage.read_json("brands.json", [])


def save_brands(brands):
    storage.write_json("brands.json", brands)


def load_music():
    return storage.read_json("music/music.json", [])


def save_music(tracks):
    storage.write_json("music/music.json", tracks)


# ---------- auth: one shared password, stored as a cookie ----------

def _session_value():
    return hmac.new(PASSWORD.encode(), b"reelcut-session", hashlib.sha256).hexdigest()


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    open_paths = (path in ("/", "/manifest.json", "/sw.js", "/icon.svg", "/api/login")
                  or path.startswith("/public/") or path.endswith("/callback"))
    if PASSWORD and not open_paths:
        if not hmac.compare_digest(request.cookies.get("rc", ""), _session_value()):
            return JSONResponse({"error": "login"}, status_code=401)
    return await call_next(request)


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    if PASSWORD and not hmac.compare_digest(body.get("password", ""), PASSWORD):
        raise HTTPException(401, "Wrong password")
    r = JSONResponse({"ok": True})
    r.set_cookie("rc", _session_value(), max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax",
                 secure=publish.base_url().startswith("https"))
    return r


# ---------- brands (company hashtags + caption style) ----------

@app.get("/api/brands")
def get_brands():
    return load_brands()


@app.post("/api/brands")
async def put_brand(request: Request):
    b = await request.json()
    brands = load_brands()
    b["id"] = b.get("id") or uuid.uuid4().hex[:10]
    b["hashtags"] = [t.strip() for t in b.get("hashtags", []) if t.strip()]
    brands = [x for x in brands if x["id"] != b["id"]] + [b]
    save_brands(brands)
    return b


@app.delete("/api/brands/{bid}")
def del_brand(bid: str):
    save_brands([x for x in load_brands() if x["id"] != bid])
    return {"ok": True}


# ---------- music library (your own royalty-free tracks) ----------

@app.get("/api/music")
def get_music():
    return load_music()


@app.post("/api/music")
async def add_music(file: UploadFile = File(...), name: str = Form(""), mood: str = Form("")):
    tid = uuid.uuid4().hex[:10]
    ext = os.path.splitext(file.filename or "")[1][:6].lower() or ".mp3"
    storage.save_upload(f"music/{tid}{ext}", file.file)
    track = {"id": tid, "file": tid + ext, "name": name.strip() or os.path.splitext(file.filename or "track")[0],
             "mood": mood.strip()}
    save_music(load_music() + [track])
    return track


@app.delete("/api/music/{tid}")
def del_music(tid: str):
    tracks = load_music()
    for t in tracks:
        if t["id"] == tid:
            storage.delete(f"music/{t['file']}")
    save_music([t for t in tracks if t["id"] != tid])
    return {"ok": True}


@app.get("/music/{tid}")
def music_file(tid: str):
    t = next((t for t in load_music() if t["id"] == tid), None)
    if not t:
        raise HTTPException(404)
    return FileResponse(storage.path(f"music/{t['file']}"))


# ---------- connect Instagram / TikTok ----------

@app.get("/api/accounts")
def accounts():
    return publish.status()


@app.get("/auth/{platform}/start")
def auth_start(platform: str):
    if platform == "instagram":
        return RedirectResponse(publish.instagram_login_url())
    if platform == "tiktok":
        return RedirectResponse(publish.tiktok_login_url())
    raise HTTPException(404)


@app.get("/auth/{platform}/callback")
def auth_callback(platform: str, code: str = "", state: str = "", error: str = "",
                  error_description: str = ""):
    try:
        if error or not code:
            raise RuntimeError(error_description or error or "Login was cancelled")
        if platform == "instagram":
            publish.instagram_callback(code.split("#")[0], state)
        elif platform == "tiktok":
            publish.tiktok_callback(code, state)
        else:
            raise HTTPException(404)
        msg = f"{platform.title()} connected ✅"
    except Exception as e:
        msg = f"Couldn't connect {platform.title()}: {e}"
    return HTMLResponse(f"<meta name=viewport content='width=device-width'><body style='font:18px sans-serif;"
                        f"background:#0f0f12;color:#fff;padding:24px'><p>{msg}</p><p><a style='color:#e8336b'"
                        f" href='/'>Back to ReelCut</a></p>")


@app.post("/api/accounts/{platform}/disconnect")
def auth_disconnect(platform: str):
    publish.disconnect(platform)
    return {"ok": True}


# ---------- jobs ----------

@app.get("/api/status")
def status():
    return {"accounts": publish.status(), "ai": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/api/jobs")
async def create_job(files: list[UploadFile] = File(...), brand_id: str = Form(""),
                     auto_post: str = Form(""), notes: str = Form(""), video_type: str = Form(""),
                     hashtags_on: str = Form("1"), extra_hashtags: str = Form(""),
                     music: str = Form("none"), hook: str = Form(""), caption: str = Form("")):
    jid = uuid.uuid4().hex[:12]
    indir = os.path.join(JOBS, jid, "in")
    os.makedirs(indir)
    names = []
    for i, f in enumerate(sorted(files, key=lambda f: f.filename or "")):
        ext = os.path.splitext(f.filename or "")[1][:6] or ".mp4"
        dest = os.path.join(indir, f"{i:03d}{ext}")
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out, 4 * 1024 * 1024)
        names.append(f.filename)
    job = {
        "id": jid, "created": time.time(), "status": "queued", "stage": "Waiting",
        "brand_id": brand_id, "auto_post": auto_post == "1", "notes": notes,
        "video_type": video_type, "hashtags_on": hashtags_on == "1",
        "extra_hashtags": [t for t in extra_hashtags.replace(",", " ").split() if t], "music": music,
        "hook": hook.strip(), "caption": caption.strip(),
        "files": names, "result": None, "error": None, "posts": {},
        "public_token": secrets.token_urlsafe(16),
    }
    save_job(job)
    work.put(jid)
    return job


@app.get("/api/jobs")
def list_jobs():
    out = []
    for jid in os.listdir(JOBS):
        try:
            out.append(load_job(jid))
        except HTTPException:
            pass
    return sorted(out, key=lambda j: -j["created"])[:50]


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    return load_job(jid)


@app.post("/api/jobs/{jid}/caption")
async def set_caption(jid: str, request: Request):
    job = load_job(jid)
    job["result"]["caption"] = (await request.json())["caption"]
    save_job(job)
    return job


@app.post("/api/jobs/{jid}/post")
async def post_job(jid: str, request: Request):
    targets = (await request.json()).get("targets", [])
    job = load_job(jid)
    if job["status"] != "done":
        raise HTTPException(400, "Video not ready")
    threading.Thread(target=do_post, args=(jid, targets), daemon=True).start()
    return {"ok": True}


@app.post("/api/jobs/{jid}/redo")
def redo_job(jid: str):
    update_job(jid, status="queued", stage="Waiting", error=None)
    work.put(jid)
    return {"ok": True}


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    shutil.rmtree(_job_path(jid), ignore_errors=True)
    return {"ok": True}


@app.get("/files/{jid}/{name}")
def job_file(jid: str, name: str):
    if name not in ("final.mp4", "thumb.jpg"):
        raise HTTPException(404)
    p = os.path.join(_job_path(jid), "out", name)
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, filename=f"reel-{jid}.mp4" if name.endswith("mp4") else None)


@app.get("/public/{jid}/{token}/final.mp4")
def public_video(jid: str, token: str):
    """Unguessable link Instagram downloads the reel from."""
    job = load_job(jid)
    if not hmac.compare_digest(token, job.get("public_token", "")):
        raise HTTPException(404)
    return FileResponse(os.path.join(_job_path(jid), "out", "final.mp4"), media_type="video/mp4")


# ---------- worker ----------

def do_post(jid, targets):
    job = load_job(jid)
    live = publish.connected()
    video = os.path.join(_job_path(jid), "out", "final.mp4")
    caption = job["result"]["caption"]
    for t in targets:
        if t not in live:
            continue
        posts = load_job(jid)["posts"]
        posts[t] = {"status": "posting"}
        update_job(jid, posts=posts)
        try:
            if t == "instagram":
                r = publish.post_instagram(f"{publish.base_url()}/public/{jid}/{job['public_token']}/final.mp4", caption)
            else:
                r = publish.post_tiktok(video, caption)
            posts[t] = {"status": "posted", **r}
        except Exception as e:
            posts[t] = {"status": "failed", "error": str(e)[:400]}
        update_job(jid, posts=posts)


def worker():
    while True:
        jid = work.get()
        cleanup()
        try:
            job = load_job(jid)
            brand = next((b for b in load_brands() if b["id"] == job["brand_id"]), None)
            library = [{**t, "path": storage.path(f"music/{t['file']}")} for t in load_music()]
            choice = job.get("music", "none")
            track = next((t for t in library if t["id"] == choice), None)
            opts = {
                "video_type": job.get("video_type", ""), "notes": job.get("notes", ""),
                "hashtags_on": job.get("hashtags_on", True), "extra_hashtags": job.get("extra_hashtags", []),
                "music": track["path"] if track else choice, "music_name": track["name"] if track else "",
                "music_library": library,
                "hook": job.get("hook", ""), "caption": job.get("caption", ""),
            }
            indir = os.path.join(_job_path(jid), "in")
            clips = [os.path.join(indir, f) for f in sorted(os.listdir(indir))]
            update_job(jid, status="processing", stage="Starting")
            result = pipeline.process(clips, os.path.join(_job_path(jid), "out"), brand, opts,
                                      progress=lambda s: update_job(jid, stage=s))
            job = update_job(jid, status="done", stage="Ready", result=result)
            if job["auto_post"]:
                do_post(jid, publish.connected())
        except Exception as e:
            traceback.print_exc()
            update_job(jid, status="failed", stage="Failed", error=str(e)[:600])


def cleanup():
    """Free hosting has limited disk: drop edits older than KEEP_DAYS."""
    for jid in os.listdir(JOBS):
        try:
            if time.time() - load_job(jid)["created"] > KEEP_DAYS * 86400:
                shutil.rmtree(_job_path(jid), ignore_errors=True)
        except HTTPException:
            shutil.rmtree(os.path.join(JOBS, jid), ignore_errors=True)


@app.on_event("startup")
def start():
    try:
        storage.restore()
    except Exception as e:
        print(f"could not restore saved brands/music/accounts: {e}")
    cleanup()
    for jid in os.listdir(JOBS):
        try:
            if load_job(jid)["status"] in ("queued", "processing"):
                work.put(jid)
        except HTTPException:
            pass
    threading.Thread(target=worker, daemon=True).start()


# ---------- phone app ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/{name}")
def static_file(name: str):
    if name not in ("manifest.json", "sw.js", "icon.svg"):
        raise HTTPException(404)
    return FileResponse(os.path.join(STATIC, name))
