"""Harness Memory (§6) — local persistent knowledge store.

Storage: SQLite (no heavy vector DB per §4). Chunks + metadata live in one
table; embeddings live as float32 blobs and search is a brute-force cosine
scan, which is plenty fast for thousands of personal notes.

Embedding strategy (device-capability aware, per owner decision):
- Try the active local runtime's /embeddings endpoint first (LM Studio /
  Ollama can serve embedding models with no extra RAM cost on this process).
- If unavailable/too heavy → keyword/BM25-lite fallback. `mode: auto` picks
  whichever works and remembers it; users can force a mode in Settings.

Privacy boundary (§10): `search()` may ONLY be called from request paths that
are flagged local. The router layer enforces this; see routers/chat.py.
"""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import struct
import threading
import time
from pathlib import Path

from ..config import DB_PATH, MEMORY_DIR
from .providers import LocalModelProvider

_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _lock, _db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS memory_files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
            kind TEXT DEFAULT 'note',          -- note | upload | folder
            size INTEGER DEFAULT 0,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_chunks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES memory_files(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            heading TEXT DEFAULT '',           -- markdown heading path
            embedding BLOB,                    -- float32 array or NULL (keyword-only)
            embed_dim INTEGER DEFAULT 0,
            sha TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunk_file ON memory_chunks(file_id);
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        """)


# ---------- chunking ----------

def chunk_text(text: str, size: int = 800, overlap: int = 120) -> list[tuple[str, str]]:
    """Split into (heading_path, chunk) pairs on paragraph boundaries."""
    lines = text.splitlines()
    blocks, cur, heading = [], [], ""
    for ln in lines:
        m = re.match(r"^(#{1,6})\s+(.*)", ln)
        if m:
            if any(s.strip() for s in cur):
                blocks.append((heading, "\n".join(cur).strip()))
                cur = []
            heading = m.group(2).strip()
        else:
            cur.append(ln)
            if sum(len(x) + 1 for x in cur) >= size:
                blocks.append((heading, "\n".join(cur).strip()))
                cur = []
    if any(s.strip() for s in cur):
        blocks.append((heading, "\n".join(cur).strip()))
    # merge tiny blocks, enforce max size with overlap slicing
    out: list[tuple[str, str]] = []
    for h, b in blocks:
        if not b:
            continue
        while len(b) > size:
            out.append((h, b[:size]))
            b = b[size - overlap:]
        if out and len(b) < 80 and out[-1][0] == h and len(out[-1][1]) + len(b) < size:
            out[-1] = (h, out[-1][1] + "\n\n" + b)
        else:
            out.append((h, b))
    return out


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------- BM25-lite keyword scoring (fallback path) ----------

_TOK = re.compile(r"[a-z0-9]+")

def _tokenize(text: str) -> list[str]:
    return _TOK.findall(text.lower())


# ---------- ingest ----------

async def ingest_text(name: str, content: str, provider: LocalModelProvider | None,
                      cfg: dict, kind: str = "note", path: str | None = None) -> dict:
    """Chunk → embed → store. Re-ingest replaces prior chunks for same path."""
    mem_cfg = cfg["memory"]
    path = path or f"mem://{name}"
    now = time.time()
    chunks = chunk_text(content, mem_cfg["chunk_size"], mem_cfg["chunk_overlap"])
    texts = [c[1] for c in chunks]
    embeddings: list[list[float]] | None = None
    used_mode = "keyword"
    if provider and mem_cfg["mode"] in ("auto", "embedding"):
        try:
            embeddings = await provider.embed(texts)
        except Exception:
            embeddings = None
        if embeddings and len(embeddings) == len(texts):
            used_mode = "embedding"
    if embeddings is None:
        embeddings = [None] * len(texts)

    with _lock, _db() as conn:
        conn.execute("DELETE FROM memory_chunks WHERE file_id IN "
                     "(SELECT id FROM memory_files WHERE path=?)", (path,))
        conn.execute("DELETE FROM memory_files WHERE path=?", (path,))
        cur = conn.execute(
            "INSERT INTO memory_files(name,path,kind,size,updated_at) VALUES(?,?,?,?,?)",
            (name, path, kind, len(content), now))
        fid = cur.lastrowid
        for (heading, text), emb in zip(chunks, embeddings):
            sha = hashlib.sha1(text.encode("utf-8")).hexdigest()
            blob = _pack(emb) if emb else None
            conn.execute(
                "INSERT INTO memory_chunks(file_id,text,heading,embedding,embed_dim,sha,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (fid, text, heading, blob, len(emb) if emb else 0, sha, now))
        conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('last_mode',?)", (used_mode,))
    return {"file": name, "chunks": len(chunks), "embedded": used_mode == "embedding",
            "mode": used_mode}


def delete_file(file_id: int) -> bool:
    with _lock, _db() as conn:
        n = conn.execute("DELETE FROM memory_files WHERE id=?", (file_id,)).rowcount
        conn.execute("DELETE FROM memory_chunks WHERE file_id=?", (file_id,))
        return n > 0


def get_file_content(file_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT id,name,path,kind,size,updated_at FROM memory_files WHERE id=?",
                           (file_id,)).fetchone()
        if not row:
            return None
        parts = conn.execute(
            "SELECT text FROM memory_chunks WHERE file_id=? ORDER BY id", (file_id,)).fetchall()
    return {"id": row[0], "name": row[1], "path": row[2], "kind": row[3],
            "size": row[4], "updated_at": row[5], "content": "\n\n".join(p[0] for p in parts)}


def list_files(limit: int = 500) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT f.id,f.name,f.kind,f.size,f.updated_at,COUNT(c.id) "
            "FROM memory_files f LEFT JOIN memory_chunks c ON c.file_id=f.id "
            "GROUP BY f.id ORDER BY f.updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r[0], "name": r[1], "kind": r[2], "size": r[3],
             "updated_at": r[4], "chunks": r[5]} for r in rows]


# ---------- retrieval ----------

async def search(query: str, provider: LocalModelProvider | None, cfg: dict,
                 top_k: int | None = None) -> list[dict]:
    """Return top matching chunks. Used ONLY on local-model request paths."""
    top_k = top_k or cfg["memory"]["top_k"]
    mode = cfg["memory"]["mode"]
    with _db() as conn:
        rows = conn.execute(
            "SELECT c.id,c.text,c.heading,f.name,c.embedding,f.path "
            "FROM memory_chunks c JOIN memory_files f ON f.id=c.file_id").fetchall()
    if not rows:
        return []

    scored: list[tuple[float, dict]] = []
    want_embed = mode in ("auto", "embedding")
    qvec = None
    if want_embed and provider:
        try:
            embs = await provider.embed([query])
            if embs and len(embs) == 1 and embs[0]:
                qvec = embs[0]
        except Exception:
            qvec = None

    if qvec:
        for cid, text, heading, fname, blob, path in rows:
            if not blob:
                continue
            vec = _unpack(blob)
            if len(vec) != len(qvec):
                continue
            scored.append((_cosine(qvec, vec), {
                "id": cid, "text": text, "heading": heading, "source": fname,
                "path": path, "score": 0.0, "method": "embedding"}))
    else:
        # BM25-lite: tf * idf-ish over the corpus we already loaded
        qtoks = set(_tokenize(query))
        if not qtoks:
            return []
        docs_toks = [(cid, text, heading, fname, path, _tokenize(text))
                     for cid, text, heading, fname, _, path in rows]
        df = {}
        for d in docs_toks:
            for t in set(d[5]):
                df[t] = df.get(t, 0) + 1
        n = len(docs_toks)
        avg_len = sum(len(d[5]) for d in docs_toks) / max(n, 1)
        k1, b = 1.5, 0.75
        for cid, text, heading, fname, path, toks in docs_toks:
            if not toks:
                continue
            score = 0.0
            tl = len(toks)
            for t in qtoks:
                tf = toks.count(t)
                if not tf:
                    continue
                idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * tl / avg_len))
            if score > 0:
                scored.append((score, {
                    "id": cid, "text": text, "heading": heading, "source": fname,
                    "path": path, "score": 0.0, "method": "keyword"}))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for s, item in scored[:top_k]:
        item["score"] = round(s, 4)
        out.append(item)
    return out


def build_context_block(hits: list[dict]) -> str:
    """Format retrieved chunks for prompt injection (local turns only)."""
    if not hits:
        return ""
    parts = ["## Retrieved from Harness Memory (local only)"]
    for h in hits:
        loc = f"{h['source']}" + (f" › {h['heading']}" if h["heading"] else "")
        parts.append(f"### {loc}  [{h['method']}, score {h['score']}]\n{h['text']}")
    return "\n\n".join(parts)
