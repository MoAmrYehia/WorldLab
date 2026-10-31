"""Turn a recorded run (runs/<id>/events.jsonl) into a static replay file the
web app plays without a server: open index.html?replay=replay.json, or put
replay.json next to index.html."""
from __future__ import annotations

import json
import time
from pathlib import Path

DROP_KINDS = {"agent"}                       # duplicated by ledger agent_step entries
DROP_LEDGER = {"trial_options"}              # large and not shown


def export(run_dir: str | Path, out: str | Path, max_images: int = 8, note: str | None = None) -> dict:
    data = build(run_dir, max_images, note)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return {**data["meta"], "bytes": out.stat().st_size, "file": str(out)}


def _compact(step: dict, limit: int = 900) -> dict:
    out = dict(step)
    for k in ("args", "result"):
        if k in out and len(json.dumps(out[k], default=str)) > limit:
            v = out[k]
            out[k] = {kk: vv for kk, vv in v.items() if len(json.dumps(vv, default=str)) < 300} if isinstance(v, dict) else str(v)[:limit]
    return out


def build(run_dir: str | Path, max_images: int = 8, note: str | None = None) -> dict:
    run_dir = Path(run_dir)
    src = run_dir / "events.jsonl"
    msgs, images, agent = [], 0, None
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        m = json.loads(line)
        k, d = m.get("kind"), m.get("data")
        if k in DROP_KINDS:
            continue
        if k == "reset" and msgs:
            break                                   # the next season's start, written by older servers: not part of this run
        if k == "reset" and isinstance(d, dict):
            agent = d.get("agent", agent)
        if k == "ledger":
            if d.get("kind") in DROP_LEDGER:
                continue
            if d.get("kind") == "agent_step":
                role = (d.get("data") or {}).get("role")
                if role not in ("agent", "tool_call", "tool_result"):
                    continue
                if role != "agent":         # the agent's tool calls, kept small for the agent trace
                    d = {**d, "data": _compact(d["data"])}
            if d.get("kind") == "session":
                agent = (d.get("data") or {}).get("agent", agent)
        if k == "scene":
            images += 1
            if images > max_images:
                d = {**d, "image": None}
        msgs.append({"t": m.get("t", 0), "kind": k, "data": d})
    if not any(m["kind"] == "mission" for m in msgs):
        msgs = _with_missions(msgs)
    if not any(m["kind"] == "reset" for m in msgs[:3]):
        msgs.insert(0, {"t": msgs[0]["t"] if msgs else 0, "kind": "reset", "data": {"agent": agent}})
    meta = {"agent": agent, "run": run_dir.name, "exported": time.strftime("%Y-%m-%d %H:%M"), "messages": len(msgs)}
    if note:
        meta["note"] = note
    return {"meta": meta, "messages": msgs}


def _with_missions(msgs: list[dict]) -> list[dict]:
    """Older recordings: add the mission progress the live server would have published."""
    from .lab import Lab
    from .progression import evaluate
    out, ledger, pert = [], [], []
    for m in msgs:
        out.append(m)
        if m["kind"] == "perturbation":
            pert.append(m["data"])
        if m["kind"] == "ledger":
            ledger.append(m["data"])
            if m["data"].get("kind") in Lab.MISSION_KINDS:
                out.append({"t": m["t"], "kind": "mission", "data": evaluate(ledger, pert)})
    return out
