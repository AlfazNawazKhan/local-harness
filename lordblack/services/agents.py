"""Agent builder & local hosting (§9).

Agents = manifest (JSON, or YAML if PyYAML is installed) with:
  name, system_prompt, model(s), allowed_tools[], trigger, rate limit.
Hosted at /agents/<name> — reachable from localhost AND LAN (owner decision),
so hosted-agent calls run in a constrained context:
  - memory access only if the manifest explicitly allows it
  - external delegation only if allowed AND internet switch is on
  - per-agent token-bucket rate limiting
  - NO folder/filesystem tools exposed to hosted endpoints in v1
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..config import AGENT_DIR, load_config
from . import pipeline

VALID_TOOLS = {"memory", "external_api", "folder_read"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,48}$")

# naive yaml subset parser so manifests work without PyYAML
def _parse_yaml(text: str) -> dict:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        pass
    out, stack = {}, [(0, None)]
    cur = out
    parents = {0: out}
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if line.startswith("- "):
            continue  # list items handled inline below
        m = re.match(r"([A-Za-z_][\w-]*):\s*(.*)", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        target = parents.get(indent, out)
        if v == "":
            child = {}
            target[k] = child
            parents[indent + 2] = child
        else:
            if v.startswith("[") and v.endswith("]"):
                target[k] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
            elif v.lower() in ("true", "false"):
                target[k] = v.lower() == "true"
            else:
                target[k] = v.strip("'\"")
    return out


def _manifest_path(name: str) -> Path:
    for ext in (".json", ".yaml", ".yml"):
        p = AGENT_DIR / f"{name}{ext}"
        if p.exists():
            return p
    return AGENT_DIR / f"{name}.json"


def save_agent(manifest: dict) -> dict:
    name = (manifest.get("name") or "").lower()
    if not _NAME_RE.match(name):
        raise ValueError("Agent name must be lowercase letters/digits/-/_ (2-49 chars).")
    manifest["name"] = name
    manifest.setdefault("system_prompt", "You are a helpful local agent.")
    manifest.setdefault("models", [])
    manifest.setdefault("allowed_tools", ["memory"])
    manifest.setdefault("trigger", "manual")
    manifest.setdefault("rate_limit_per_min", 10)
    bad = set(manifest["allowed_tools"]) - VALID_TOOLS
    if bad:
        raise ValueError(f"Unknown tools: {bad}. Valid: {VALID_TOOLS}")
    path = AGENT_DIR / f"{name}.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_agent(name: str) -> dict | None:
    if not _NAME_RE.match(name.lower()):
        return None
    p = _manifest_path(name.lower())
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    return json.loads(txt) if p.suffix == ".json" else _parse_yaml(txt)


def list_agents() -> list[dict]:
    out = []
    for p in sorted(AGENT_DIR.iterdir()):
        if p.suffix in (".json", ".yaml", ".yml"):
            try:
                m = load_agent(p.stem)
                if m:
                    m["_file"] = p.name
                    out.append(m)
            except Exception:
                continue
    return out


def delete_agent(name: str) -> bool:
    p = _manifest_path(name.lower())
    if p.exists():
        p.unlink()
        return True
    return False


# ---------- rate limiting (token bucket per agent) ----------
_buckets: dict[str, list[float]] = {}


def _rate_ok(agent_name: str, limit_per_min: int) -> bool:
    now = time.time()
    hits = [t for t in _buckets.get(agent_name, []) if now - t < 60]
    if len(hits) >= max(1, limit_per_min):
        return False
    hits.append(now)
    _buckets[agent_name] = hits
    return True


async def invoke_agent(name: str, user_text: str, history: list[dict] | None = None,
                       stream: bool = True):
    """Run an agent turn through the same privacy-enforced pipeline."""
    manifest = load_agent(name)
    if not manifest:
        raise KeyError(f"No such agent: {name}")
    cfg = load_config()
    tools = set(manifest.get("allowed_tools", []))
    if not _rate_ok(name, int(manifest.get("rate_limit_per_min",
                                           cfg["agents"].get("rate_limit_per_min", 20)))):
        raise RuntimeError("Rate limit exceeded for this hosted agent.")
    # Constrained execution: tools simply aren't passed unless whitelisted (§9/§10)
    models = [m for m in (manifest.get("models") or []) if isinstance(m, str) and m.strip()]
    async for ev in pipeline.run_turn(
        user_text, history or [],
        agentic="external_api" in tools and cfg["cloud"]["enabled"],
        use_memory="memory" in tools,
        mode="single", allow_external="external_api" in tools,
        system_prefix=manifest.get("system_prompt"),
        model_override=(models[0] if models else None), cfg=cfg):
        yield ev
