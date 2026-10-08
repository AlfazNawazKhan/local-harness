"""Scoped folder access (§8).

The user grants specific folders; nothing outside a granted root is reachable.
Per-file enable/disable toggles decide what the model may actually read.
Path traversal is blocked by realpath containment checks.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..config import load_config, save_config


def _real_within(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except (ValueError, RuntimeError):
        return False


def grant_folder(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists() or not p.is_dir():
        raise ValueError(f"Not a directory: {path}")
    cfg = load_config()
    rid = f"fld-{abs(hash(str(p.resolve()))) % 10**8}"
    entry = {"id": rid, "path": str(p.resolve()), "name": p.name or str(p),
             "enabled": True, "granted_at": time.time(),
             "disabled_files": []}
    cfg["folders"] = [f for f in cfg["folders"] if f["path"] != entry["path"]]
    cfg["folders"].append(entry)
    save_config(cfg)
    return entry


def revoke_folder(folder_id: str) -> bool:
    cfg = load_config()
    before = len(cfg["folders"])
    cfg["folders"] = [f for f in cfg["folders"] if f["id"] != folder_id]
    save_config(cfg)
    return len(cfg["folders"]) < before


def set_file_toggle(folder_id: str, rel_path: str, enabled: bool) -> dict:
    cfg = load_config()
    for f in cfg["folders"]:
        if f["id"] == folder_id:
            dis = set(f.get("disabled_files", []))
            dis.add(rel_path) if not enabled else dis.discard(rel_path)
            f["disabled_files"] = sorted(dis)
            save_config(cfg)
            return f
    raise KeyError(folder_id)


def list_folders() -> list[dict]:
    return load_config()["folders"]


def tree(folder_id: str, sub: str = "", depth_limit: int = 200) -> dict:
    """Lazy listing: only the requested directory level is walked (§4)."""
    cfg = load_config()
    fld = next((f for f in cfg["folders"] if f["id"] == folder_id), None)
    if not fld:
        raise KeyError(folder_id)
    root = Path(fld["path"])
    base = root / sub if sub else root
    if not _real_within(root, base):
        raise PermissionError("Path escapes granted folder")
    items = []
    disabled = set(fld.get("disabled_files", []))
    try:
        entries = sorted(base.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        return {"folder": fld, "sub": sub, "items": [], "error": "OS permission denied"}
    count = 0
    for e in entries:
        if e.name.startswith(".") or count >= depth_limit:
            continue
        rel = str(e.relative_to(root))
        if e.is_dir():
            items.append({"rel": rel, "name": e.name, "type": "dir",
                          "children_hint": _quick_count(e)})
        else:
            items.append({"rel": rel, "name": e.name, "type": "file",
                          "size": e.stat().st_size,
                          "enabled": rel not in disabled,
                          "text_ok": e.suffix.lower() in
                                     (".txt", ".md", ".py", ".js", ".json", ".yaml", ".yml",
                                      ".csv", ".html", ".css", ".toml", ".ini", ".sh", ".bat")})
        count += 1
    return {"folder": fld, "sub": sub, "items": items}


def _quick_count(d: Path) -> int:
    try:
        return sum(1 for _ in d.iterdir())
    except Exception:
        return -1


def read_file(folder_id: str, rel_path: str, max_bytes: int = 64_000) -> dict:
    """Read a granted, individually-enabled file. Enforces §8 scoping."""
    cfg = load_config()
    fld = next((f for f in cfg["folders"] if f["id"] == folder_id), None)
    if not fld:
        raise KeyError(folder_id)
    if not fld.get("enabled", True):
        raise PermissionError("Folder access revoked.")
    root = Path(fld["path"])
    target = root / rel_path
    if not _real_within(root, target):
        raise PermissionError("Path escapes granted folder")
    if rel_path in set(fld.get("disabled_files", [])):
        raise PermissionError(f"File '{rel_path}' is toggled OFF by the user.")
    if not target.is_file():
        raise FileNotFoundError(rel_path)
    data = target.read_bytes()[:max_bytes]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"rel": rel_path, "binary": True, "size": target.stat().st_size}
    return {"rel": rel_path, "binary": False, "content": text,
            "truncated": target.stat().st_size > max_bytes}
