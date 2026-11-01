"""Package one run as an offline evidence bundle: the complete raw ledger, a manifest and the verifier.

  python scripts/build_evidence.py RUN_DIR OUT_DIR [--source-commit SHA] [--source-note TEXT]

The manifest carries the run's identity and provenance (source commit, prompt and tool-schema hashes, model IDs,
seed, hidden events, perception mode, timestamps, completion status, usage) and the artifact hashes, including the
ledger's final hash. No API keys, headers, account details or server paths are included.
"""
import argparse
import gzip
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def tool_hashes(commit: str | None) -> dict:
    """Prompt and tool-schema hashes for the source the run was made with (from git when a commit is given)."""
    import subprocess
    src = None
    if commit:
        try:
            src = subprocess.run(["git", "show", f"{commit}:worldlab/agent.py"], capture_output=True, text=True, timeout=10, cwd=ROOT).stdout
        except Exception:
            src = None
    if src:
        ns = {"__name__": "worldlab._agent_at_commit", "__package__": "worldlab"}
        exec(compile(src, "agent.py", "exec"), ns)
        prompt, tools = ns["SYSTEM_PROMPT"], ns["TOOLS"]
    else:
        from worldlab.agent import SYSTEM_PROMPT as prompt, TOOLS as tools
    return {"prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "tool_schema_sha256": hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest(), "tools": len(tools)}


def source_trees(commit: str | None) -> dict:
    """Git tree hashes of the simulator and the whole package at the run's commit: anchors the run to released source."""
    import subprocess
    out = {}
    for key, path in (("simulator_tree", "worldlab/farm"), ("package_tree", "worldlab")):
        try:
            r = subprocess.run(["git", "rev-parse", f"{commit}:{path}"], capture_output=True, text=True, timeout=10, cwd=ROOT)
            out[key] = r.stdout.strip() or None
        except Exception:
            out[key] = None
    from worldlab import __version__
    out["package_version"] = __version__
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--source-commit", default=None)
    ap.add_argument("--source-note", default=None)
    a = ap.parse_args()
    run, out = Path(a.run_dir), Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = (run / "ledger.jsonl").read_bytes()
    L = [json.loads(x) for x in raw.decode().splitlines() if x.strip()]
    st = json.loads((run / "settings.json").read_text())
    kinds = lambda k: [e for e in L if e["kind"] == k]
    end = (kinds("run_end") or [{"data": {}}])[-1]["data"]
    res = (kinds("season_result") or [{"data": {}}])[-1]["data"]
    model = next((s["data"]["text"].split("model ", 1)[1] for s in kinds("agent_step")
                  if s["data"].get("role") == "system" and "model " in str(s["data"].get("text", ""))), None)
    looks = kinds("look")
    usage = (kinds("model_usage") or [{"data": None}])[-1]["data"]
    gz = gzip.compress(raw, mtime=0)
    (out / "ledger.jsonl.gz").write_bytes(gz)
    shutil.copy(ROOT / "scripts" / "verify_evidence.py", out / "verify_evidence.py")
    m = {"schema": "worldlab.evidence/1", "run": run.name,
         "source": {"commit": a.source_commit, "note": a.source_note, **tool_hashes(a.source_commit),
                    **(source_trees(a.source_commit) if a.source_commit else {})},
         "scientist": {"agent": st["agent"], "model": model},
         "perception": {"mode": st.get("perception"), "models": ["sam-3.1", "muse-spark-1.3"] if st.get("perception") == "meta" else [],
                        "images": "synthetic renders of the simulator's state", "looks": len(looks)},
         "farm": {"seed": st["seed"], "scenario": st.get("scenario"), "hidden_events": st.get("perturb"),
                  "limits": st.get("limits") or "defaults (60,000 m3 groundwater, 90,000 kWh)", "hard_budget": True},
         "timestamps": {"first_entry": L[0]["wall"], "last_entry": L[-1]["wall"]},
         "status": end.get("status") or ("completed" if res else "unknown"),
         "result": {k: res.get(k) for k in ("people_fed", "water_used_m3", "energy_used_kwh", "within_quota", "within_energy")} if res else None,
         "usage": usage or {"scientist_tool_calls_recorded": sum(1 for e in kinds("agent_step") if e["data"].get("role") == "tool_call"),
                            "note": "this run predates per-run token accounting; the count is of recorded tool calls"},
         "artifacts": {"ledger.jsonl.gz": {"sha256_gz": hashlib.sha256(gz).hexdigest(), "sha256": hashlib.sha256(raw).hexdigest(),
                                           "entries": len(L), "head": L[-1]["hash"]}},
         "guarantee": ("The hash chain detects any edit, reordering or removal relative to the final hash recorded here and in the "
                       "repository. It does not by itself prove that a model was called or that the agronomy is correct."),
         "verify": "python verify_evidence.py ."}
    (out / "manifest.json").write_text(json.dumps(m, indent=1))
    (out / "README.txt").write_text(
        "WorldLab evidence bundle\n\nmanifest.json      what this run is, where it came from, and the hashes\n"
        "ledger.jsonl.gz    the complete raw ledger (every entry, uncompacted)\nverify_evidence.py checks the ledger against the manifest\n\n"
        "To verify (Python 3, no installs):  python verify_evidence.py .\n\n" + m["guarantee"] + "\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in ("manifest.json", "ledger.jsonl.gz", "verify_evidence.py", "README.txt"):
            z.write(out / f, f"worldlab-evidence/{f}")
    (out / "worldlab-evidence.zip").write_bytes(buf.getvalue())
    print(json.dumps({"run": run.name, "entries": len(L), "head": L[-1]["hash"][:16], "status": m["status"]}))


if __name__ == "__main__":
    main()
