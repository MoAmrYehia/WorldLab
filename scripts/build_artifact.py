"""Build a static, server-free copy of the web app (replay mode) into a folder.
--fragment strips the document wrapper for hosts that add their own."""
import re, shutil, sys
from pathlib import Path

src = Path(__file__).resolve().parent.parent / "worldlab" / "dashboard"
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
html = (src / "index.html").read_text()
if "--fragment" in sys.argv:
    html = re.sub(r"<!doctype html>\s*|</?html[^>]*>\s*|</?head>\s*|</?body>\s*", "", html, flags=re.I)
    html = re.sub(r'<meta charset="utf-8">\s*<meta name="viewport"[^>]*>\s*', "", html)
(out / "index.html").write_text(html)
for f in ("app.js", "scene.js", "style.css", "replay.json"):
    shutil.copy(src / f, out / f)
print(out)
