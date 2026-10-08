"""/api/files — scoped folder access (§8).

Everything here is confined to folders the user explicitly granted; per-file
toggles decide what the chat pipeline may attach. No endpoint returns content
for a revoked folder or an individually-disabled file.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import activity, fileaccess

router = APIRouter(prefix="/api/files", tags=["files"])


class GrantReq(BaseModel):
    path: str


@router.get("/folders")
async def folders():
    return {"folders": fileaccess.list_folders()}


@router.post("/grant")
async def grant(req: GrantReq):
    try:
        entry = fileaccess.grant_folder(req.path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    activity.log("file-access", "ok", f"granted {entry['path']}")
    return entry


class RevokeReq(BaseModel):
    id: str


@router.post("/revoke")
async def revoke(req: RevokeReq):
    ok = fileaccess.revoke_folder(req.id)
    if ok:
        activity.log("file-access", "ok", f"revoked {req.id}")
    return {"revoked": ok}


class ToggleReq(BaseModel):
    folder_id: str
    rel: str
    enabled: bool


@router.post("/toggle")
async def toggle(req: ToggleReq):
    try:
        fileaccess.set_file_toggle(req.folder_id, req.rel, req.enabled)
    except KeyError:
        raise HTTPException(404, "Unknown folder id")
    return {"ok": True}


class TreeReq(BaseModel):
    folder_id: str
    sub: str = ""


@router.post("/tree")
async def tree(req: TreeReq):
    """Lazy, level-at-a-time listing (§4: don't walk huge trees eagerly)."""
    try:
        return fileaccess.tree(req.folder_id, req.sub)
    except KeyError:
        raise HTTPException(404, "Unknown folder id")
    except PermissionError as e:
        raise HTTPException(403, str(e))


class ReadReq(BaseModel):
    folder_id: str
    rel: str


@router.post("/read")
async def read(req: ReadReq):
    try:
        return fileaccess.read_file(req.folder_id, req.rel)
    except KeyError:
        raise HTTPException(404, "Unknown folder id")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
