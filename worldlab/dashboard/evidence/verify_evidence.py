#!/usr/bin/env python3
"""Verify a WorldLab evidence bundle offline, with nothing but Python's standard library.

  python verify_evidence.py BUNDLE_DIR        (the folder holding manifest.json and ledger.jsonl.gz)

Checks, in order:
  1. the compressed ledger's SHA-256 matches the manifest
  2. every entry's hash matches its content, and each entry points to the previous one (no edits, no reordering,
     nothing removed from the middle)
  3. the number of entries and the final hash match the manifest (nothing cut off the end)

What this proves: the ledger is the same, entry for entry, as the one whose final hash is recorded in the manifest
(and in the repository's history). It does not prove that a model was actually called, or that the agronomy is right.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

GENESIS = "0" * 64


def digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify(bundle: Path) -> tuple[bool, str]:
    m = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    art = m["artifacts"]["ledger.jsonl.gz"]
    blob = (bundle / "ledger.jsonl.gz").read_bytes()
    if hashlib.sha256(blob).hexdigest() != art["sha256_gz"]:
        return False, "the compressed ledger is not the file named in the manifest (SHA-256 differs)"
    raw = gzip.decompress(blob)
    if hashlib.sha256(raw).hexdigest() != art["sha256"]:
        return False, "the ledger content differs from the manifest (SHA-256 differs)"
    prev, n = GENESIS, 0
    for i, line in enumerate(raw.decode("utf-8").splitlines()):
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("prev") != prev:
            return False, f"chain broken at entry {i} (seq {e.get('seq')}): it does not follow the previous entry"
        if digest(e) != e.get("hash"):
            return False, f"entry {i} (seq {e.get('seq')}) was altered: its hash doesn't match its content"
        prev, n = e["hash"], n + 1
    if n != art["entries"]:
        return False, f"{n} entries, the manifest says {art['entries']}"
    if prev != art["head"]:
        return False, "the final hash doesn't match the manifest: entries were removed from the end or added"
    return True, f"ok: {n} entries, chain intact, final hash {prev[:16]}… matches the manifest"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    ok, msg = verify(Path(sys.argv[1]))
    print(("VERIFIED " if ok else "FAILED ") + msg)
    sys.exit(0 if ok else 1)
