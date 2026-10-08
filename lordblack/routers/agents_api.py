"""/api/agents + /agents/{name} — Agent builder & local hosting (§9).

Two surfaces:
  /api/agents/*      the in-app dashboard (Settings → Node Networks) — CRUD,
                     run-now, manifest validation. Local UI only.
  /agents/{name}     the *hosted* endpoint other local tools/scripts call.
                     Reachable from localhost AND LAN (owner decision), so it
                     runs through the constrained path in services/agents.py:
                     whitelisted tools only, per-agent rate limit, and the
                     same §10 memory boundary as the chat pipeline.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import load_config
from ..services import activity, agents
from ..services.agents import VALID_TOOLS

router = APIRouter(tags=["agents"])


# ---------------- dashboard API ----------------
class ManifestReq(BaseModel):
    name: str
    system_prompt: str = "You are a helpful local agent."
    models: list[str] = []
    allowed_tools: list[str] = ["memory"]
    trigger: str = "manual"              # manual | scheduled | endpoint
    rate_limit_per_min: int = 10
    description: str = ""


@router.get("/api/agents")
async def list_agents():
    cfg = load_config()
    return {"agents": agents.list_agents(),
            "valid_tools": sorted(VALID_TOOLS),
            "host_enabled": cfg["agents"]["host_enabled"],
            "allow_lan": cfg["agents"].get("allow_lan", True)}


@router.post("/api/agents")
async def create_agent(req: ManifestReq):
    try:
        m = agents.save_agent(req.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    activity.log("agent-builder", "ok", f"saved agent '{m['name']}' "
                                        f"(tools={m['allowed_tools']})")
    return m


class DeleteReq(BaseModel):
    name: str


@router.post("/api/agents/delete")
async def delete_agent(req: DeleteReq):
    return {"deleted": agents.delete_agent(req.name)}


class RunReq(BaseModel):
    message: str
    history: list[dict] = []
    stream: bool = True


@router.post("/api/agents/{name}/run")
async def run_agent(name: str, req: RunReq):
    """Dashboard 'Run now' button — full trace events, same SSE shape as chat."""
    async def gen():
        try:
            async for ev in agents.invoke_agent(name, req.message, req.history):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'done','answer':'','error':str(e)[:300]})}\n\n"
    if req.stream:
        return StreamingResponse(gen(), media_type="text/event-stream")
    answer, trace = "", []
    async for ev in agents.invoke_agent(name, req.message, req.history):
        if ev.get("type") == "trace":
            trace.append(ev)
        elif ev.get("type") == "done":
            answer = ev.get("answer", "")
    return {"answer": answer, "trace": trace}


# ---------------- hosted endpoint (LAN-reachable) ----------------
@router.post("/agents/{name}")
async def host_agent(name: str, body: dict, request: Request):
    """Machine-to-machine endpoint: POST {"message": "..."} -> JSON reply.

    Constrained context (§9): no file attachments accepted here, tools limited
    to the manifest whitelist, rate-limited per agent. Non-streaming by design
    so calling scripts stay simple; use /api/agents/{name}/run for traces.
    """
    cfg = load_config()
    if not cfg["agents"].get("host_enabled", True):
        raise HTTPException(503, "Agent hosting is disabled in Settings.")
    msg = (body or {}).get("message") or ""
    if not isinstance(msg, str) or not msg.strip():
        raise HTTPException(400, "Body must be JSON with a non-empty 'message'.")
    if len(msg) > 20_000:
        raise HTTPException(413, "Message too large for hosted agent endpoint.")
    activity.log("agent-host", "start", f"{request.client.host if request.client else '?'} "
                                        f"→ /agents/{name}")
    try:
        answer, meta = "", {}
        async for ev in agents.invoke_agent(name, msg):
            if ev.get("type") == "done":
                answer, meta = ev.get("answer", ""), ev
        return {"agent": name, "answer": answer,
                "model": meta.get("model", ""), "runtime": meta.get("runtime", ""),
                "latency_ms": meta.get("total_ms", 0)}
    except KeyError:
        raise HTTPException(404, f"No such hosted agent: {name}")
    except RuntimeError as e:      # rate limit
        raise HTTPException(429, str(e))
    except Exception as e:
        activity.log("agent-host", "fail", f"{name}: {str(e)[:160]}")
        raise HTTPException(502, f"Agent run failed: {str(e)[:200]}")


@router.get("/agents")
async def hosted_index():
    """Human-friendly index of hosted endpoints for curl/scripts."""
    cfg = load_config()
    items = []
    for a in agents.list_agents():
        items.append({"name": a.get("name"),
                      "endpoint": f"/agents/{a.get('name')}",
                      "tools": a.get("allowed_tools", []),
                      "trigger": a.get("trigger", "manual"),
                      "rate_limit_per_min": a.get("rate_limit_per_min", 10)})
    return {"hosting": cfg["agents"].get("host_enabled", True),
            "lan_exposed": cfg["agents"].get("allow_lan", True), "agents": items}
