"""/api/system/* — config read/write, runtime health + model detection (§5),
live stats SSE and the raw activity log console (§11)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import __version__, system_stats
from ..config import load_config, save_config
from ..services import activity, fileaccess
from ..services.providers import DEFAULT_URLS, ProviderError, get_provider

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/config")
async def get_cfg():
    cfg = load_config()
    # never leak key material through config (keys live in secure_store only)
    return cfg


@router.post("/config")
async def patch_cfg(body: dict):
    """Shallow-merged partial update of settings (General / Security / Memory…)."""
    cfg = load_config()

    def merge(dst: dict, src: dict):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v

    merge(cfg, body or {})
    save_config(cfg)
    activity.log("settings", "ok", "configuration updated")
    return {"ok": True}


@router.get("/health")
async def health():
    """Top-bar online/offline + local-runtime reachability."""
    cfg = load_config()
    try:
        provider = get_provider(cfg["runtime"]["active"], cfg["runtime"].get("base_url"))
        prov_health = await provider.health_check()
    except ProviderError as e:
        prov_health = {"ok": False, "error": str(e)}
    return {"app": "LordBlack Harness", "version": __version__,
            "internet": bool(cfg["cloud"]["enabled"]),
            "runtime": cfg["runtime"]["active"], "provider": prov_health}


@router.post("/connect")
async def connect(body: dict):
    """Settings → 'LM Studio / Local Hub' Connect/Test Connection button.

    Probes the given runtime+URL and, on success, auto-detects models
    (the mockup's 'Detection active: Found Qwen (7B/14B) & Gemma models')."""
    runtime = body.get("runtime") or load_config()["runtime"]["active"]
    url = (body.get("base_url") or "").strip() or DEFAULT_URLS.get(runtime, "")
    try:
        provider = get_provider(runtime, url)
    except ProviderError as e:
        return {"ok": False, "error": str(e), "models": []}
    h = await provider.health_check()
    if not h.get("ok"):
        return {"ok": False, "error": h.get("error") or f"Runtime not reachable at {url}",
                "models": []}
    try:
        models = await provider.list_models()
    except Exception as e:
        models = []
        h["models_error"] = str(e)[:200]
    if body.get("save", True):
        cfg = load_config()
        cfg["runtime"]["active"] = runtime
        cfg["runtime"]["base_url"] = url
        if models and not any(m["id"] == cfg["runtime"].get("model") for m in models):
            cfg["runtime"]["model"] = models[0]["id"]
        save_config(cfg)
        activity.log("local-routing", "ok", f"connected to {runtime} @ {url}, "
                                            f"{len(models)} models detected")
    return {"ok": True, "runtime": runtime, "base_url": url, "models": models,
            "detail": f"Detection active: found {len(models)} model(s)"}


@router.get("/stats")
async def stats_once():
    return system_stats.sample()


@router.get("/stats/stream")
async def stats_stream():
    """SSE feed powering the bottom status bar sparkline (§4: push, don't poll)."""
    async def gen():
        async for s in system_stats.stream():
            yield f"data: {json.dumps(s)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/logs")
async def logs(limit: int = 100):
    return {"events": activity.recent(limit)}


@router.get("/logs/stream")
async def logs_stream():
    async def gen():
        async for line in activity.stream():
            yield f"data: {line}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.get("/summary")
async def summary():
    """Everything the workspace needs on first paint, in one round-trip."""
    cfg = load_config()
    return {"config": cfg, "version": __version__,
            "folders": fileaccess.list_folders(),
            "agents": [a.get("name") for a in _agents_safe()],
            "memory_mode": cfg["memory"]["mode"]}


def _agents_safe():
    try:
        from ..services.agents import list_agents
        return list_agents()
    except Exception:
        return []
