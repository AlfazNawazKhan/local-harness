"""/api/cloud — external provider connections + encrypted key management (§7/§10).

Key handling rules enforced here:
- Keys arrive over localhost HTTP only, are immediately encrypted at rest via
  secure_store, and the plaintext is never echoed back except through the
  explicit reveal endpoint.
- List/status responses always carry the masked form (sk-ant-••••••abcd).
- Every call path in services/cloud.py short-circuits when cfg.cloud.enabled
  is False, so turning the Internet switch off makes these providers inert.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import load_config, save_config
from ..services import activity, cloud
from ..services.secure_store import delete_api_key, mask_key, reveal_key, set_api_key

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


class KeyReq(BaseModel):
    provider: str
    api_key: str
    default_model: str | None = None


@router.get("/providers")
async def providers():
    cfg = load_config()
    out = []
    for name, meta in cloud.PROVIDER_DEFAULTS.items():
        stored = cfg["cloud"].get("providers", {}).get(name, {})
        out.append({"id": name, "label": meta["label"], "base_url": meta["base_url"],
                    "connected": bool(stored.get("connected")),
                    "default_model": stored.get("default_model", ""),
                    "has_key": mask_key(name) is not None,
                    "masked_key": mask_key(name)})
    return {"internet_enabled": cfg["cloud"]["enabled"],
            "prefer_free_openrouter": cfg["cloud"].get("prefer_free_openrouter", True),
            "providers": out}


@router.post("/key")
async def save_key(req: KeyReq):
    if req.provider not in cloud.PROVIDER_DEFAULTS:
        raise HTTPException(400, f"Unknown provider '{req.provider}'")
    key = req.api_key.strip()
    if len(key) < 8:
        raise HTTPException(400, "API key looks too short to be valid.")
    set_api_key(req.provider, key)
    cfg = load_config()
    cfg["cloud"].setdefault("providers", {})[req.provider] = {
        "connected": True,
        "default_model": req.default_model or
                         cfg["cloud"].get("providers", {}).get(req.provider, {})
                         .get("default_model", "")}
    save_config(cfg)
    activity.log("external-api", "ok", f"{req.provider} API key stored (encrypted)")
    return {"ok": True, "masked": mask_key(req.provider)}


class ProviderReq(BaseModel):
    provider: str


@router.post("/verify")
async def verify(req: ProviderReq):
    """Settings 'Verify' button — cheap authenticated probe."""
    cfg = load_config()
    if not cfg["cloud"]["enabled"]:
        return {"ok": False, "detail": "Internet access is OFF (Settings → Security). "
                                       "Enable it to verify cloud providers."}
    res = await cloud.verify_provider(req.provider, cfg)
    activity.log("external-api", "ok" if res["ok"] else "fail",
                 f"verify {req.provider}: {res['detail'][:120]}")
    return res


@router.post("/disconnect")
async def disconnect(req: ProviderReq):
    delete_api_key(req.provider)
    cfg = load_config()
    cfg["cloud"].get("providers", {}).pop(req.provider, None)
    save_config(cfg)
    activity.log("external-api", "ok", f"{req.provider} disconnected, key deleted")
    return {"ok": True}


@router.post("/reveal")
async def reveal(req: ProviderReq):
    """Explicit user action; UI shows it briefly and never persists it."""
    k = reveal_key(req.provider)
    if not k:
        raise HTTPException(404, "No key stored for that provider")
    return {"provider": req.provider, "api_key": k}


@router.get("/openrouter/models")
async def openrouter_models():
    """Live free-model catalog for the delegation picker (§7)."""
    cfg = load_config()
    if not cfg["cloud"]["enabled"]:
        return {"free": [], "all_count": 0,
                "detail": "Internet OFF — showing curated fallback list.",
                "fallback": cloud.FREE_OPENROUTER_FALLBACK}
    try:
        from ..services.secure_store import get_api_key
        info = await cloud.list_openrouter_models(get_api_key("openrouter"))
        info["fallback"] = cloud.FREE_OPENROUTER_FALLBACK
        return info
    except Exception as e:
        return {"error": str(e)[:200], "free": [], "all_count": 0,
                "fallback": cloud.FREE_OPENROUTER_FALLBACK}
