WorldLab evidence bundle

manifest.json      what this run is, where it came from, and the hashes
ledger.jsonl.gz    the complete raw ledger (every entry, uncompacted)
verify_evidence.py checks the ledger against the manifest

To verify (Python 3, no installs):  python verify_evidence.py .

The hash chain detects any edit, reordering or removal relative to the final hash recorded here and in the repository. It does not by itself prove that a model was called or that the agronomy is correct.
