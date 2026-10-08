"""The chat pipeline — routing, memory injection, delegation, local-to-local (§7).

Emits a structured activity trace (for the right-hand AI Activity panel) as an
async generator of SSE-ready events:  {"type": "trace"|"token"|"done", ...}

Privacy enforcement lives HERE, at the routing layer (§10):
- Memory search runs only when `allow_memory=True`, which is set only for turns
  whose final answer comes from a LocalModelProvider.
- The external-delegation branch receives only the sub-task string the local
  model itself wrote inside <delegate> tags — never raw memory chunks. We strip
  the injected memory block from anything that could be forwarded outbound.
"""
from __future__ import annotations

import json
import re
import time
from typing import AsyncIterator

from .. import __version__
from ..config import load_config
from . import activity, cloud, fileaccess, memory
from .providers import get_provider

DELEGATE_RE = re.compile(
    r"<delegate\s+provider=\"(?P<provider>[a-z]+)\"\s+need=\"(?P<need>[^\"]*)\">\s*(?P<task>.{3,2000}?)\s*</delegate>",
    re.S | re.I)

LOCAL_SYSTEM = (
    "You are LordBlack Harness, a private local AI assistant. "
    "Harness Memory context may be provided below; treat it as your own long-term memory.\n"
    "You may consult outside experts for a specific sub-task by emitting EXACTLY this block "
    "(the harness will execute it and continue your turn):\n"
    '<delegate provider="openrouter|anthropic|openai" need="what you need back">'
    "self-contained sub-task question here</delegate>\n"
    "Never include private memory content inside a delegate block — describe only what you need. "
    "If no help is needed, just answer normally."
)


def _now() -> float:
    return time.time()


class Tracer:
    def __init__(self):
        self.events: list[dict] = []

    def event(self, step: str, status: str, detail: str = "", ms: int = 0) -> dict:
        ev = {"type": "trace", "step": step, "status": status, "detail": detail,
              "ms": ms, "ts": _now()}
        self.events.append(ev)
        activity.log(step, status, detail, ms)   # mirror into the raw log console
        return ev

    def token(self, text: str, speaker: str = "") -> dict:
        return {"type": "token", "tok": text, **({"speaker": speaker} if speaker else {})}


async def run_turn(user_text: str, history: list[dict], *,
                   agentic: bool = True, use_memory: bool = True,
                   mode: str = "single", partner: str | None = None,
                   rounds: int = 2, allow_external: bool = True,
                   attached_files: list[dict] | None = None,
                   system_prefix: str | None = None,
                   model_override: str | None = None,
                   cfg: dict | None = None) -> AsyncIterator[dict]:
    """mode: 'single' (one local model, optional delegation) or
       'dialog' (local-to-local planner↔worker chat, §7).

    system_prefix lets hosted agents (§9) swap in their own persona while
    keeping the same privacy-enforced routing."""
    cfg = cfg or load_config()
    tr = Tracer()
    rt_cfg = cfg["runtime"]
    provider = get_provider(rt_cfg["active"], rt_cfg.get("base_url"))

    t0 = _now()
    yield tr.event("input-parsed", "ok", f"{len(user_text)} chars")
    yield tr.event("local-routing", "ok",
                   f"runtime={rt_cfg['active']} url={rt_cfg.get('base_url')}")

    # ---- memory retrieval: LOCAL PATH ONLY (§6/§10 hard boundary) ----
    mem_block = ""
    if use_memory and cfg["memory"]["top_k"] >= 0:
        t1 = _now()
        hits = await memory.search(user_text, provider, cfg)
        ms = int((_now() - t1) * 1000)
        mem_block = memory.build_context_block(hits)
        yield tr.event("memory-search", "ok",
                       f"{len(hits)} chunks ({hits[0]['method'] if hits else 'n/a'})", ms)
        for h in hits:
            yield {"type": "retrieval", "source": h["source"], "heading": h["heading"],
                   "score": h["score"], "method": h["method"],
                   "preview": h["text"][:140].replace("\n", " ")}

    model = rt_cfg.get("model") or ""
    if not model:
        try:
            models = await provider.list_models()
            model = models[0]["id"] if models else ""
        except Exception:
            model = ""
    if not model:
        yield tr.event("error", "fail", "No local model available. Check LM Studio / runtime.")
        yield {"type": "done", "answer": "", "error": "no-model"}
        return

    sys_msg = {"role": "system",
               "content": (system_prefix + "\n\n" if system_prefix else "") + LOCAL_SYSTEM +
                          (("\n\n" + mem_block) if mem_block else "")}

    class _LocalGen:
        """Streams tokens AND records the full text (async generators can't
        `return` a value, so callers read .text after the loop)."""

        def __init__(self):
            self.text = ""

        async def run(self, messages, mdl, temperature=None):
            pieces = []
            async for tok in provider.chat(messages, mdl, stream=True,
                                           temperature=temperature or rt_cfg.get("temperature", 0.7),
                                           max_tokens=max(512, rt_cfg.get("context_tokens", 2048) // 2)):
                pieces.append(tok)
                yield tok
            self.text = "".join(pieces)

    # ================= local-to-local dialog mode =================
    if mode == "dialog" and partner:
        worker = partner
        planner_model = model
        topic = user_text
        transcript = []
        yield tr.event("local-dialog", "start",
                       f"planner={planner_model} ↔ worker={worker}, rounds={rounds}")
        current_prompt = (f"You are the PLANNER in a two-local-model session. Goal: {topic}\n"
                          "Give the WORKER one concrete instruction or question to advance the goal.")
        for i in range(max(1, rounds)):
            speaker = "planner" if i % 2 == 0 else "worker"
            mdl = planner_model if speaker == "planner" else worker
            msgs = [sys_msg] + [{"role": "user",
                                 "content": "Conversation so far:\n" + "\n\n".join(transcript) +
                                            f"\n\nYOUR TURN ({speaker}): {current_prompt}"}] \
                if transcript else [sys_msg, {"role": "user", "content": current_prompt}]
            t2 = _now()
            gen = _LocalGen()
            buf = []
            async for tok in gen.run(msgs, mdl):
                buf.append(tok)
                yield tr.token(tok, speaker)
            reply = gen.text or "".join(buf)
            transcript.append(f"[{speaker}/{mdl}]: {reply}")
            yield tr.event(f"dialog-turn-{i+1}", "ok", f"{speaker}: {mdl}",
                           int((_now() - t2) * 1000))
            current_prompt = "Respond to the other model. Refine, critique, or extend. Be concise."
        yield {"type": "done", "answer": "\n\n".join(transcript),
               "trace": tr.events, "total_ms": int((_now() - t0) * 1000)}
        return

    # ================= single-model mode (+ delegation loop) =================
    # Optional file context: user-toggled files from granted folders (§8).
    # Local-only path — file contents are injected into the LOCAL system prompt
    # and never forwarded to an external provider (§10 hard boundary).
    file_ctx = ""
    for fc in (attached_files or []):
        try:
            r = fileaccess.read_file(fc["folder"], fc["rel"], max_bytes=12_000)
            if not r.get("binary"):
                file_ctx += f"\n\n### File: {fc['rel']}\n```\n{r['content'][:8000]}\n```"
            yield tr.event("file-access", "ok" if not r.get("binary") else "skip",
                           fc["rel"])
        except Exception as e:
            yield tr.event("file-access", "blocked", f"{fc['rel']}: {str(e)[:120]}")

    messages = [{"role": "system",
                 "content": sys_msg["content"] +
                            (("\n\n## User-granted working files (local only)" + file_ctx)
                             if file_ctx else "")}] \
        + history[-8:] + [{"role": "user", "content": user_text}]
    full_answer_parts: list[str] = []
    delegations_made = 0
    max_delegations = 2 if (agentic and allow_external) else 0

    while True:
        t3 = _now()
        gen = _LocalGen()
        buf = []
        async for tok in gen.run(messages, model):
            buf.append(tok)
            yield tr.token(tok)
        reply = gen.text or "".join(buf)
        yield tr.event("local-generation", "ok", f"{model}", int((_now() - t3) * 1000))

        m = DELEGATE_RE.search(reply) if max_delegations else None
        if not m:
            clean = DELEGATE_RE.sub("", reply).strip() or reply.strip()
            full_answer_parts.append(clean)
            break

        provider_name, need, task = m.group("provider"), m.group("need"), m.group("task")
        # ---- §10 HARD BOUNDARY: outbound scrubbing -------------------------------
        # Anything destined for an external/cloud model is stripped of local-only
        # content: retrieved memory lines, granted-file lines, and fenced file
        # blocks. The delegate `task` the local model wrote is the only thing sent.
        fence = re.search(r"```.*?```", task, flags=re.S)
        if fence:
            task = task.replace(fence.group(0), "[redacted-local-file-block]")
        for src in filter(None, (mem_block, file_ctx)):
            for line in src.splitlines():
                s = line.strip()
                if len(s) > 40 and s in task:
                    task = task.replace(s, "[redacted-local-context]")
        yield tr.event("routing-decision", "ok",
                       f"local model requests external help → {provider_name}")
        delegations_made += 1
        try:
            if not cfg["cloud"]["enabled"] or provider_name not in cfg["cloud"].get("providers", {}):
                raise cloud.CloudDisabled("Internet access OFF or provider not connected.")
            chosen = await cloud.pick_model(provider_name, cfg)
            yield tr.event("external-call", "start", f"{provider_name}:{chosen}")
            t4 = _now()
            res = await cloud.call_external(provider_name, chosen,
                                            cloud.EXTRACT_PROMPT + task, cfg)
            yield tr.event("external-call", "ok", f"{res['latency_ms']} ms", res["latency_ms"])
            extracted = await cloud.extract_relevant(res["text"], need, provider_name, cfg)
            yield tr.event("response-extraction", "ok", f"{len(extracted)} chars kept")
            messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content":
                    f"[HARNESS] External result from {provider_name}/{chosen} for \"{need}\":\n"
                    f"{extracted}\nNow fold this into your final answer. Do not emit another "
                    f"delegate block unless truly necessary."}]
            max_delegations -= 1
        except cloud.CloudDisabled as e:
            yield tr.event("external-call", "blocked", str(e)[:160])
            note = f"\n\n> ⚠ External delegation unavailable: {e}"
            full_answer_parts.append(DELEGATE_RE.sub("", reply).strip() + note)
            break
        except Exception as e:
            yield tr.event("external-call", "fail", str(e)[:160])
            full_answer_parts.append(DELEGATE_RE.sub("", reply).strip() +
                                     f"\n\n> ⚠ Delegation failed: {str(e)[:120]}")
            break

    yield {"type": "done", "answer": "\n\n".join(full_answer_parts),
           "trace": tr.events, "model": model, "runtime": rt_cfg["active"],
           "total_ms": int((_now() - t0) * 1000)}
