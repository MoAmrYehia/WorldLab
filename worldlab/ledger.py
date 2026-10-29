"""Append-only, hash-chained experiment ledger.

Every hypothesis, prediction, experiment, measurement summary, model update,
anomaly and decision is written here as one JSON line. Each entry carries the
SHA-256 of the previous entry, so editing or deleting any line afterwards
breaks the chain and `python -m worldlab.ledger verify FILE` reports where.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

GENESIS = "0" * 64


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Ledger:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.entries: list[dict] = []
        self._prev = GENESIS
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("")

    def append(self, kind: str, data: dict, t_rig: float | None = None) -> dict:
        with self._lock:
            entry = {"seq": len(self.entries), "wall": round(time.time(), 3), "t": t_rig,
                     "kind": kind, "data": data, "prev": self._prev}
            entry["hash"] = _digest(entry)
            self._prev = entry["hash"]
            self.entries.append(entry)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")
            return entry


def verify(path: str | Path) -> tuple[bool, str]:
    prev = GENESIS
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("prev") != prev:
            return False, f"chain broken at line {i + 1} (seq {e.get('seq')}): prev hash mismatch"
        if _digest(e) != e.get("hash"):
            return False, f"entry altered at line {i + 1} (seq {e.get('seq')}): hash mismatch"
        prev = e["hash"]
    return True, f"ok: {len(lines)} entries, chain intact, head {prev[:16]}"


def load(path: str | Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "verify":
        print("usage: python -m worldlab.ledger verify RUN.jsonl")
        sys.exit(2)
    ok, msg = verify(sys.argv[2])
    print(msg)
    sys.exit(0 if ok else 1)
