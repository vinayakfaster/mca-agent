"""
file_store.py - per-user file storage for uploads and generated outputs.

Layout on disk (DATA_DIR defaults to ./agent_data):
    agent_data/users/<safe_user_id>/files/<file_id><ext>     the file itself
    agent_data/users/<safe_user_id>/files/<file_id>.json     small metadata record

Used by files_api.py (HTTP) and by tools (via ctx["user_id"]).
"""
import json
import os
import re
import time
import uuid
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "agent_data")).resolve()
MAX_UPLOAD_BYTES = int(float(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024)
MAX_FILES_PER_USER = int(os.getenv("MAX_FILES_PER_USER", "200"))

# Only these types are accepted. SVG and HTML are deliberately NOT allowed
# (they can carry scripts). Add an extension here when a new module needs it.
ALLOWED_EXT = {
    ".pdf", ".txt", ".md", ".csv", ".xlsx", ".xls", ".json",
    ".zip", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".png", ".jpg", ".jpeg",
}
INLINE_EXT = {".png", ".jpg", ".jpeg"}   # shown in the browser; everything else downloads

_ID_RE = re.compile(r"^[a-f0-9]{16}$")


class FileStoreError(Exception):
    """A problem the caller can show to the user (bad type, too many files, ...)."""


def safe_user_id(user_id: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.@-]", "_", (user_id or "").strip())[:64].lstrip(".")
    if not s:
        raise FileStoreError("Invalid user id.")
    return s


def user_dir(user_id: str) -> Path:
    d = (DATA_DIR / "users" / safe_user_id(user_id) / "files").resolve()
    if DATA_DIR not in d.parents:          # belt and braces against path tricks
        raise FileStoreError("Invalid user id.")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean_name(filename: str) -> str:
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f]", "", name).strip()
    return name[:120] or "upload"


def save_bytes(user_id: str, filename: str, data: bytes, generated: bool = False) -> dict:
    name = _clean_name(filename)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise FileStoreError(f"File type '{ext or 'unknown'}' is not allowed.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileStoreError(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    d = user_dir(user_id)
    if len(list(d.glob("*.json"))) >= MAX_FILES_PER_USER:
        raise FileStoreError("File limit reached. Delete some files first.")
    file_id = uuid.uuid4().hex[:16]
    (d / f"{file_id}{ext}").write_bytes(data)
    meta = {"id": file_id, "name": name, "ext": ext, "size": len(data),
            "uploaded": int(time.time()), "generated": bool(generated)}
    (d / f"{file_id}.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def get_file(user_id: str, file_id: str):
    """Return (path, meta). Raises FileNotFoundError if it does not exist for this user."""
    if not _ID_RE.match(file_id or ""):
        raise FileNotFoundError(file_id)
    d = user_dir(user_id)
    meta_path = d / f"{file_id}.json"
    if not meta_path.is_file():
        raise FileNotFoundError(file_id)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    path = d / f"{file_id}{meta['ext']}"
    if not path.is_file():
        raise FileNotFoundError(file_id)
    return path, meta


def list_files(user_id: str) -> list:
    out = []
    for p in user_dir(user_id).glob("*.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda m: m.get("uploaded", 0), reverse=True)


def delete_file(user_id: str, file_id: str) -> None:
    path, meta = get_file(user_id, file_id)
    path.unlink(missing_ok=True)
    (path.parent / f"{file_id}.json").unlink(missing_ok=True)
