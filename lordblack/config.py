"""Runtime configuration for LordBlack Harness.

Everything persists to a single JSON file inside the data directory so the
app stays clone-and-run with no external DB service. Secrets are never stored
in this file (see secure_store.py).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("LORDBLACK_DATA", Path(__file__).parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "harness.db"
MEMORY_DIR = DATA_DIR / "memory"          # user memory files (md/txt) live here too
AGENT_DIR = DATA_DIR / "agents"           # agent manifests (YAML/JSON)
KEYFILE_PATH = DATA_DIR / ".master.key"   # local-only key material, 0600 perms

MEMORY_DIR.mkdir(parents=True, exist_ok=True)
AGENT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    # Local runtime hub
    "runtime": {
        "active": "lmstudio",              # lmstudio | ollama | llamacpp
        "base_url": "http://localhost:1234/v1",
        "model": "",                       # selected model id ("" = first detected)
        "context_tokens": 2048,            # conservative default; raise on beefier boxes
        "temperature": 0.7,
    },
    # Memory / RAG
    "memory": {
        "mode": "auto",                    # auto | embedding | keyword  (§4 device-capability based)
        "top_k": 4,                        # chunks injected per turn — conservative
        "chunk_size": 800,                 # chars
        "chunk_overlap": 120,
    },
    # Cloud delegation
    "cloud": {
        "enabled": False,                  # master internet switch (§8)
        "providers": {},                   # {name: {"base_url":..., "connected": bool}}
        "prefer_free_openrouter": True,
    },
    # Device access
    "folders": [],                         # [{id, path, name, enabled}]
    "bluetooth": {"enabled": False},
    # Agents / node networks
    "agents": {"host_enabled": True, "allow_lan": True, "rate_limit_per_min": 20},
    # UI prefs
    "ui": {"log_level": "info"},
}

_lock = threading.Lock()


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    with _lock:
        if CONFIG_PATH.exists():
            try:
                saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                return _deep_merge(DEFAULTS, saved)
            except Exception:
                pass  # corrupted file → fall back to defaults rather than crash
        cfg = json.loads(json.dumps(DEFAULTS))
        save_config(cfg)
        return cfg


def save_config(cfg: dict) -> None:
    with _lock:
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
