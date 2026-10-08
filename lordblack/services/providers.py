"""LocalModelProvider abstraction (§5).

One implementation per runtime — LM Studio, Ollama, llama.cpp server — all
normalized behind: list_models(), chat(messages, stream), embed(text),
health_check(). The rest of the app never needs to know which runtime is live.

All providers talk plain HTTP via httpx so nothing here requires a GPU or a
heavy native dependency; the models themselves run in the user's own runtime.
"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx


class ProviderError(RuntimeError):
    pass


class LocalModelProvider(ABC):
    name: str = "base"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    async def health_check(self) -> dict: ...

    @abstractmethod
    async def list_models(self) -> list[dict]: ...

    @abstractmethod
    def chat(self, messages: list[dict], model: str, *, stream: bool = True,
             temperature: float = 0.7, max_tokens: int = 1024) -> AsyncIterator[str]: ...

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Optional; None means this runtime can't embed (caller falls back)."""
        return None


class _OpenAICompatProvider(LocalModelProvider):
    """Shared implementation for LM Studio and llama.cpp server (/v1 endpoints)."""

    name = "openai-compat"

    async def health_check(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self.base_url}/models")
                ok = r.status_code < 500
                return {"ok": ok, "status": r.status_code, "runtime": self.name}
        except Exception as e:
            return {"ok": False, "error": str(e), "runtime": self.name}

    async def list_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base_url}/models")
            r.raise_for_status()
            data = r.json().get("data", [])
        out = []
        for m in data:
            mid = m.get("id") or m.get("name") or ""
            if mid:
                out.append({"id": mid, "name": mid})
        return out

    async def chat(self, messages, model, *, stream=True, temperature=0.7, max_tokens=1024):
        payload = {"model": model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "stream": stream}
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as c:
            if not stream:
                r = await c.post(f"{self.base_url}/chat/completions", json=payload)
                r.raise_for_status()
                yield r.json()["choices"][0]["message"]["content"]
                return
            async with c.stream("POST", f"{self.base_url}/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                        delta = obj["choices"][0].get("delta", {})
                        piece = delta.get("content")
                        if piece:
                            yield piece
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def embed(self, texts):
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{self.base_url}/embeddings",
                                 json={"input": texts, "model": ""})
                if r.status_code >= 400:
                    return None
                data = sorted(r.json().get("data", []), key=lambda d: d.get("index", 0))
                return [d["embedding"] for d in data]
        except Exception:
            return None


class LMStudioProvider(_OpenAICompatProvider):
    name = "lmstudio"


class LlamaCppProvider(_OpenAICompatProvider):
    name = "llamacpp"


class OllamaProvider(LocalModelProvider):
    name = "ollama"

    async def health_check(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self.base_url}/api/tags")
                return {"ok": r.status_code == 200, "status": r.status_code, "runtime": self.name}
        except Exception as e:
            return {"ok": False, "error": str(e), "runtime": self.name}

    async def list_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            models = r.json().get("models", [])
        return [{"id": m.get("name", ""), "name": m.get("name", ""),
                 "size": m.get("size", 0)} for m in models if m.get("name")]

    async def chat(self, messages, model, *, stream=True, temperature=0.7, max_tokens=1024):
        payload = {"model": model, "messages": messages, "stream": stream,
                   "options": {"temperature": temperature, "num_ctx": max_tokens}}
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as c:
            if not stream:
                r = await c.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
                yield r.json().get("message", {}).get("content", "")
                return
            async with c.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = obj.get("message", {}).get("content")
                    if piece:
                        yield piece
                    if obj.get("done"):
                        break

    async def embed(self, texts):
        try:
            out = []
            async with httpx.AsyncClient(timeout=120) as c:
                for t in texts:
                    r = await c.post(f"{self.base_url}/api/embeddings",
                                     json={"model": "", "prompt": t})
                    if r.status_code >= 400:
                        return None
                    out.append(r.json().get("embedding"))
            if any(e is None for e in out):
                return None
            return out
        except Exception:
            return None


_PROVIDERS = {
    "lmstudio": LMStudioProvider,
    "ollama": OllamaProvider,
    "llamacpp": LlamaCppProvider,
}

DEFAULT_URLS = {
    "lmstudio": "http://localhost:1234/v1",
    "ollama": "http://localhost:11434",
    "llamacpp": "http://localhost:8080/v1",
}


def get_provider(runtime: str, base_url: str | None = None) -> LocalModelProvider:
    cls = _PROVIDERS.get(runtime)
    if cls is None:
        raise ProviderError(f"Unknown runtime '{runtime}'. Choose: {', '.join(_PROVIDERS)}")
    return cls(base_url or DEFAULT_URLS[runtime])
