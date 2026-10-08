"""/api/memory — Harness Memory CRUD + upload (§6).

Notes are stored as real .md/.txt files under data/memory/ (user-auditable)
and chunked/embedded into SQLite. Uploads accept text/markdown only; binary is
rejected so the store never becomes a dumping ground for unreadable blobs.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..config import MEMORY_DIR, load_config
from ..services import memory
from ..services.providers import get_provider

router = APIRouter(prefix="/api/memory", tags=["memory"])

_ALLOWED_SUFFIX = {".md", ".markdown", ".txt"}


def _provider_or_none(cfg: dict):
    try:
        return get_provider(cfg["runtime"]["active"], cfg["runtime"].get("base_url"))
    except Exception:
        return None


class NoteReq(BaseModel):
    name: str
    content: str


@router.get("/files")
async def files():
    return {"files": memory.list_files(), "dir": str(MEMORY_DIR)}


class GetReq(BaseModel):
    id: int


@router.post("/get")
async def get_file(req: GetReq):
    f = memory.get_file_content(req.id)
    if not f:
        raise HTTPException(404, "Memory file not found")
    return f


@router.post("/note")
async def save_note(req: NoteReq):
    """Create or overwrite a note by name (add / edit share this endpoint)."""
    safe = "".join(c for c in req.name if c.isalnum() or c in "-_ .")[:80] or "note"
    if not safe.endswith((".md", ".txt")):
        safe += ".md"
    path = MEMORY_DIR / safe
    path.write_text(req.content, encoding="utf-8")
    cfg = load_config()
    res = await memory.ingest_text(safe, req.content, _provider_or_none(cfg), cfg,
                                   kind="note", path=str(path))
    return res


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    name = Path(file.filename or "upload.md").name
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise HTTPException(415, f"Only text/markdown uploads are accepted ({sorted(_ALLOWED_SUFFIX)})")
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "File too large (>2 MB) for the low-resource memory store")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    path = MEMORY_DIR / name
    path.write_text(text, encoding="utf-8")
    cfg = load_config()
    res = await memory.ingest_text(name, text, _provider_or_none(cfg), cfg,
                                   kind="upload", path=str(path))
    return res


class DeleteReq(BaseModel):
    id: int


@router.post("/delete")
async def delete(req: DeleteReq):
    f = memory.get_file_content(req.id)
    if not f:
        raise HTTPException(404, "Memory file not found")
    p = Path(f["path"])
    if p.is_relative_to(MEMORY_DIR) and p.exists():
        p.unlink()
    return {"deleted": memory.delete_file(req.id), "name": f["name"]}


class SearchReq(BaseModel):
    query: str
    top_k: int | None = None


@router.post("/search")
async def search(req: SearchReq):
    """Manual search from the Memory panel — always local-only (§10)."""
    cfg = load_config()
    hits = await memory.search(req.query, _provider_or_none(cfg), cfg, top_k=req.top_k)
    return {"query": req.query, "hits": [{k: h[k] for k in
                                          ("source", "heading", "score", "method", "text")}
                                         for h in hits]}


@router.post("/reindex")
async def reindex():
    """Re-chunk/re-embed every stored note (e.g. after switching embedding mode)."""
    cfg = load_config()
    prov = _provider_or_none(cfg)
    out = []
    for p in sorted(MEMORY_DIR.glob("*")):
        if p.suffix.lower() in _ALLOWED_SUFFIX and p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            out.append(await memory.ingest_text(p.name, text, prov, cfg,
                                                kind="note", path=str(p)))
    return {"reindexed": len(out), "results": out, "at": time.time()}
