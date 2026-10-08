"""/api/chat — the streaming pipeline endpoint (§7 + §10).

Response is Server-Sent Events so tokens stream token-by-token on a 4 GB box:
  data: {"type":"trace",...}       AI Activity panel steps
  data: {"type":"retrieval",...}   Memory Retrieval panel entries
  data: {"type":"token",...}       chat text deltas
  data: {"type":"done",...}        final answer + trace summary

Privacy boundary enforced here (not just by convention): `use_memory` and file
attachments are honoured ONLY when the turn's inference target is a local
runtime. There is no code path in this router that sends memory content to an
external provider — see pipeline.run_turn for the outbound scrubbing.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import load_config
from ..services import cloud
from ..services.pipeline import run_turn
from ..services.providers import ProviderError

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=200_000)
    history: list[dict] = []                       # [{role, content}] prior turns
    agentic: bool = True                           # allow external delegation
    use_memory: bool = True                        # RAG Memory toggle
    mode: str = "single"                           # single | dialog
    partner: str | None = None                     # worker model for local-to-local
    rounds: int = 2
    attached_files: list[dict] = []                # [{folder, rel}] toggled ON files


@router.post("/stream")
async def chat_stream(req: ChatReq):
    cfg = load_config()
    try:
        get_provider_check = cfg["runtime"]["active"]  # validated inside run_turn
    except Exception:
        raise HTTPException(400, "Runtime not configured")

    async def gen():
        try:
            async for ev in run_turn(
                    req.message, req.history,
                    agentic=req.agentic, use_memory=req.use_memory,
                    mode=req.mode, partner=req.partner, rounds=req.rounds,
                    allow_external=req.agentic, attached_files=req.attached_files,
                    cfg=cfg):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except ProviderError as e:
            yield f"data: {json.dumps({'type':'done','answer':'','error':str(e)})}\n\n"
        except Exception as e:  # never leak stack traces into the stream body
            yield f"data: {json.dumps({'type':'done','answer':'','error':str(e)[:300]})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


class TestCloudReq(BaseModel):
    provider: str
    prompt: str = "Reply with exactly: OK"


@router.post("/test-cloud")
async def test_cloud(req: TestCloudReq):
    """Settings → Cloud card 'Test' button. Sends NO user data — fixed probe."""
    cfg = load_config()
    if req.provider not in cloud.PROVIDER_DEFAULTS:
        raise HTTPException(400, f"Unknown provider '{req.provider}'")
    try:
        model = await cloud.pick_model(req.provider, cfg)
        res = await cloud.call_external(req.provider, model,
                                        "Reply with exactly: OK", cfg, max_tokens=8)
        return {"ok": True, "model": model, "reply": res["text"][:120],
                "latency_ms": res["latency_ms"]}
    except cloud.CloudDisabled as e:
        raise HTTPException(403, str(e))
    except Exception as e:
        return {"ok": False, "detail": str(e)[:300]}
