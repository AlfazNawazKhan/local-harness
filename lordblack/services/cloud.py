"""External API delegation (§7 + §10).

- Providers: OpenRouter (free-model catalog), Anthropic Claude, OpenAI.
- The master internet switch (`cloud.enabled`) makes every code path here
  fully inert when off — calls raise rather than silently proceeding.
- PRIVACY HARD BOUNDARY: nothing in this module ever receives Harness Memory
  content. `delegate()` accepts only text the *local model* explicitly wrote
  into the sub-task prompt; the router layer never passes memory chunks here.
"""
from __future__ import annotations

import json
import time
from typing import AsyncIterator

import httpx

from .secure_store import get_api_key

PROVIDER_DEFAULTS = {
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "label": "OpenRouter"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "label": "Anthropic Claude"},
    "openai": {"base_url": "https://api.openai.com/v1", "label": "OpenAI GPT"},
}

# Small curated catalog of models that have been free on OpenRouter; the live
# /models endpoint is authoritative and refreshes this list at connect-time.
FREE_OPENROUTER_FALLBACK = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-small:free",
]


class CloudDisabled(RuntimeError):
    pass


def _require_enabled(cfg: dict) -> None:
    if not cfg.get("cloud", {}).get("enabled"):
        raise CloudDisabled(
            "Internet access is OFF in Settings → Security. External delegation is inert.")


async def list_openrouter_models(api_key: str | None = None) -> dict:
    """Return {'free': [...], 'all_count': n}. Free = ':free' suffix or 0 pricing."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{PROVIDER_DEFAULTS['openrouter']['base_url']}/models", headers=headers)
        r.raise_for_status()
        data = r.json().get("data", [])
    free = []
    for m in data:
        mid = m.get("id", "")
        pricing = m.get("pricing") or {}
        is_free = mid.endswith(":free") or all(
            float(pricing.get(k, "1") or "1") == 0 for k in ("prompt", "completion"))
        if is_free:
            free.append(mid)
    return {"free": free, "all_count": len(data)}


async def verify_provider(provider: str, cfg: dict) -> dict:
    """Cheap authenticated probe used by the Settings 'Verify' button."""
    key = get_api_key(provider)
    if not key:
        return {"ok": False, "detail": "No API key stored."}
    try:
        if provider == "openrouter":
            info = await list_openrouter_models(key)
            return {"ok": True, "detail": f"Key valid. {info['all_count']} models, "
                                          f"{len(info['free'])} free."}
        if provider == "anthropic":
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{PROVIDER_DEFAULTS['anthropic']['base_url']}/models",
                                headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
            return {"ok": r.status_code < 400, "detail": f"HTTP {r.status_code}"}
        # openai
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{PROVIDER_DEFAULTS['openai']['base_url']}/models",
                            headers={"Authorization": f"Bearer {key}"})
        return {"ok": r.status_code < 400, "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:200]}


async def pick_model(provider: str, cfg: dict, task_hint: str = "") -> str:
    """Choose a suitable external model — free-first for OpenRouter (§7)."""
    if provider != "openrouter":
        defaults = {"anthropic": "claude-3-5-haiku-latest", "openai": "gpt-4o-mini"}
        return cfg["cloud"]["providers"].get(provider, {}).get("default_model") \
            or defaults.get(provider, "")
    prefer_free = cfg["cloud"].get("prefer_free_openrouter", True)
    if prefer_free:
        try:
            info = await list_openrouter_models(get_api_key("openrouter"))
            if info["free"]:
                return info["free"][0]
        except Exception:
            pass
        return FREE_OPENROUTER_FALLBACK[0]
    return cfg["cloud"]["providers"].get("openrouter", {}).get("default_model") \
        or "openrouter/auto"


async def call_external(provider: str, model: str, prompt: str, cfg: dict,
                       max_tokens: int = 700) -> dict:
    """One-shot external completion. Input must contain NO memory content —
    enforced by the caller (chat pipeline extracts the sub-task text first)."""
    _require_enabled(cfg)
    key = get_api_key(provider)
    if not key:
        raise RuntimeError(f"No API key configured for '{provider}'.")
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as c:
        if provider == "anthropic":
            r = await c.post(f"{PROVIDER_DEFAULTS['anthropic']['base_url']}/messages",
                             headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                             json={"model": model, "max_tokens": max_tokens,
                                   "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []))
        else:
            base = PROVIDER_DEFAULTS[provider]["base_url"]
            extra = {"HTTP-Referer": "http://localhost", "X-Title": "LordBlack Harness"} \
                if provider == "openrouter" else {}
            headers = {"Authorization": f"Bearer {key}", **extra}
            r = await c.post(f"{base}/chat/completions", headers=headers,
                             json={"model": model, "max_tokens": max_tokens,
                                   "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
    return {"provider": provider, "model": model, "text": text,
            "latency_ms": int((time.time() - t0) * 1000)}


EXTRACT_PROMPT = (
    "You are being consulted by a local AI assistant. Answer the sub-task below "
    "concisely and factually. Return ONLY the information needed — no preamble.\n\nSUB-TASK:\n"
)


async def extract_relevant(raw: str, need: str, provider: str, cfg: dict) -> str:
    """Second pass: pull only what the local model actually needs (§7 flow).
    Uses the same external provider; falls back to truncation if it fails."""
    try:
        model = await pick_model(provider, cfg)
        res = await call_external(
            provider, model,
            f"From the TEXT, copy out only the parts relevant to NEED. Output the extracted "
            f"information only.\n\nNEED: {need}\n\nTEXT:\n{raw[:6000]}", cfg, max_tokens=400)
        return res["text"]
    except Exception:
        return raw[:1500]
