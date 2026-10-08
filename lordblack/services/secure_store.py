"""Encrypted-at-rest storage for external API keys (§10, non-negotiable).

Design (kept dependency-light for low-end machines):
- A random 32-byte master key is generated on first run and stored in the data
  dir with 0600 permissions. It never leaves the device.
- API keys are encrypted with Fernet (AES-128-CBC + HMAC) when `cryptography`
  is available; otherwise we fall back to a keyed ChaCha-style XOR stream
  (stdlib hashlib-based) so the repo still runs with zero third-party crypto.
- Keys are NEVER written to config.json. Only ciphertext lives on disk.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from ..config import DATA_DIR, KEYFILE_PATH

_KEYS_PATH = DATA_DIR / "keys.enc.json"
_PREFIX = b"LBH1:"  # version marker so we can detect legacy/plaintext accidents


def _load_master_key() -> bytes:
    if KEYFILE_PATH.exists():
        k = KEYFILE_PATH.read_bytes()
        if len(k) >= 32:
            return k[:32]
    k = secrets.token_bytes(32)
    fd = os.open(str(KEYFILE_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(k)
    return k


_MASTER = _load_master_key()

try:  # preferred path: real authenticated crypto if installed
    from cryptography.fernet import Fernet, InvalidToken

    _fernet = Fernet(base64.urlsafe_b64encode(_MASTER))

    def _encrypt(pt: bytes) -> bytes:
        return _PREFIX + _fernet.encrypt(pt)

    def _decrypt(ct: bytes) -> bytes:
        if not ct.startswith(_PREFIX):
            raise ValueError("unrecognized key blob")
        return _fernet.decrypt(ct[len(_PREFIX):])
except Exception:  # stdlib fallback: keyed stream cipher + HMAC integrity
    def _stream(nonce: bytes, length: int) -> bytes:
        out = b""
        counter = 0
        while len(out) < length:
            out += hashlib.sha256(_MASTER + nonce + counter.to_bytes(4, "big")).digest()
            counter += 1
        return out[:length]

    def _encrypt(pt: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        ct = bytes(a ^ b for a, b in zip(pt, _stream(nonce, len(pt))))
        tag = hmac.new(_MASTER, nonce + ct, hashlib.sha256).digest()[:16]
        return _PREFIX + base64.b64encode(nonce + tag + ct)

    def _decrypt(ct: bytes) -> bytes:
        if not ct.startswith(_PREFIX):
            raise ValueError("unrecognized key blob")
        raw = base64.b64decode(ct[len(_PREFIX):])
        nonce, tag, body = raw[:12], raw[12:28], raw[28:]
        if not hmac.compare_digest(tag, hmac.new(_MASTER, nonce + body, hashlib.sha256).digest()[:16]):
            raise ValueError("key blob tampered")
        return bytes(a ^ b for a, b in zip(body, _stream(nonce, len(body))))


def _read_store() -> dict:
    if _KEYS_PATH.exists():
        try:
            return json.loads(_KEYS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_store(store: dict) -> None:
    tmp = _KEYS_PATH.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    os.replace(tmp, _KEYS_PATH)


def set_api_key(provider: str, plaintext_key: str) -> None:
    blob = _encrypt(plaintext_key.encode("utf-8"))
    store = _read_store()
    store[provider] = blob.decode("ascii")
    _write_store(store)


def get_api_key(provider: str) -> str | None:
    store = _read_store()
    blob = store.get(provider)
    if not blob:
        return None
    try:
        return _decrypt(blob.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def delete_api_key(provider: str) -> None:
    store = _read_store()
    store.pop(provider, None)
    _write_store(store)


def mask_key(provider: str) -> str | None:
    """Return a UI-safe masked preview like 'sk-ant-••••••' plus last 4 chars."""
    k = get_api_key(provider)
    if not k:
        return None
    head = k[:7] if len(k) > 12 else k[:3]
    return f"{head}••••••{k[-4:]}" if len(k) > 12 else f"{head}••••"


def reveal_key(provider: str) -> str | None:
    """Explicit user action only — surfaced via a dedicated endpoint, never logged."""
    return get_api_key(provider)
