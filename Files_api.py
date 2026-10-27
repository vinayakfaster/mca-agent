"""
files_api.py - upload / list / download / delete endpoints for the agent's files.

Hook into your existing FastAPI app (main.py) with two lines:

    from files_api import create_router
    app.include_router(create_router(YOUR_EXISTING_KEY_CHECK))

YOUR_EXISTING_KEY_CHECK is the function you already use to verify the X-API-Key header
(the one your /api/chat route depends on). Pass the function itself, not Depends(...).
If your whole app already checks the key globally, pass `lambda: None`.
The router has no default on purpose, so it can never be exposed without a decision.

Needs: pip install python-multipart
Same trust level as the rest of the app: user_id comes from the browser, like conversations.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

import file_store as fs

CHUNK = 1024 * 1024


def create_router(auth) -> APIRouter:
    router = APIRouter(prefix="/api/files", tags=["files"], dependencies=[Depends(auth)])

    @router.post("")
    async def upload(user_id: str = Query(..., min_length=1, max_length=64), file: UploadFile = File(...)):
        parts, total = [], 0
        while True:
            chunk = await file.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > fs.MAX_UPLOAD_BYTES:        # stop reading as soon as the limit is passed
                raise HTTPException(413, f"File too large (max {fs.MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
            parts.append(chunk)
        try:
            return fs.save_bytes(user_id, file.filename or "upload", b"".join(parts))
        except fs.FileStoreError as e:
            raise HTTPException(400, str(e))

    @router.get("")
    def list_all(user_id: str = Query(..., min_length=1, max_length=64)):
        try:
            return {"files": fs.list_files(user_id)}
        except fs.FileStoreError as e:
            raise HTTPException(400, str(e))

    @router.get("/{file_id}")
    def download(file_id: str, user_id: str = Query(..., min_length=1, max_length=64)):
        try:
            path, meta = fs.get_file(user_id, file_id)
        except fs.FileStoreError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "File not found.")
        inline = meta["ext"] in fs.INLINE_EXT
        return FileResponse(path, filename=meta["name"],
                            content_disposition_type="inline" if inline else "attachment",
                            headers={"X-Content-Type-Options": "nosniff"})

    @router.delete("/{file_id}")
    def remove(file_id: str, user_id: str = Query(..., min_length=1, max_length=64)):
        try:
            fs.delete_file(user_id, file_id)
        except fs.FileStoreError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "File not found.")
        return {"deleted": file_id}

    return router
