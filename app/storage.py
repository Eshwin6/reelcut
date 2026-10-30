"""Small persistent store for brands, music and account tokens.

Free Hugging Face Spaces wipe the disk on every restart, so when HF_TOKEN is set
everything in here is mirrored to a private Hugging Face dataset repo (free) and
pulled back on startup. Edited videos are not mirrored: they're temporary.
"""
import json
import os
import shutil
import threading

DATA = os.environ.get("DATA_DIR", "/data")
STORE = os.path.join(DATA, "store")
TOKEN = os.environ.get("HF_TOKEN", "")
REPO = os.environ.get("STORAGE_REPO") or (
    f"{os.environ['SPACE_AUTHOR_NAME']}/reelcut-data" if os.environ.get("SPACE_AUTHOR_NAME") else "")
SYNC = bool(TOKEN and REPO)
os.makedirs(STORE, exist_ok=True)
_lock = threading.Lock()


def _api():
    from huggingface_hub import HfApi
    return HfApi(token=TOKEN)


def restore():
    """Pull the mirrored store down at startup."""
    if not SYNC:
        return
    from huggingface_hub import snapshot_download
    _api().create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
    snapshot_download(REPO, repo_type="dataset", local_dir=STORE, token=TOKEN)


def _push(rel):
    if not SYNC:
        return

    def go():
        try:
            path = os.path.join(STORE, rel)
            if os.path.exists(path):
                _api().upload_file(path_or_fileobj=path, path_in_repo=rel, repo_id=REPO, repo_type="dataset")
            else:
                _api().delete_file(rel, repo_id=REPO, repo_type="dataset")
        except Exception as e:
            print(f"storage sync failed for {rel}: {e}")
    threading.Thread(target=go, daemon=True).start()


def path(rel):
    return os.path.join(STORE, rel)


def read_json(rel, default):
    try:
        with open(path(rel)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(rel, obj):
    with _lock:
        p = path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w") as f:
            json.dump(obj, f)
        os.replace(p + ".tmp", p)
    _push(rel)


def save_upload(rel, fileobj):
    p = path(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as out:
        shutil.copyfileobj(fileobj, out, 4 * 1024 * 1024)
    _push(rel)


def delete(rel):
    try:
        os.remove(path(rel))
    except FileNotFoundError:
        pass
    _push(rel)
