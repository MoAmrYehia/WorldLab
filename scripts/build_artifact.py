"""Build static, server-free copies of the website.

  python scripts/build_artifact.py docs            landing page at docs/, replay app at docs/app/ (GitHub Pages)
  python scripts/build_artifact.py OUT --app-only  just the replay app in OUT
  add --fragment to strip the document wrapper for hosts that add their own
"""
import re, shutil, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "worldlab"
out = Path(sys.argv[1])
app_only = "--app-only" in sys.argv
app_dir = out if app_only else out / "app"
app_dir.mkdir(parents=True, exist_ok=True)


import subprocess

try:
    VERSION = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             cwd=root.parent).stdout.strip() or "dev"
except OSError:
    VERSION = "dev"


def page(src: Path, dst: Path, sub=None):
    html = src.read_text()
    if sub:
        html = sub(html)
    # cache-busting for static hosts: refer to this build's stylesheets and scripts
    html = re.sub(r'((?:href|src)=")((?:\.\./)?(?:site|style|app|hero|config)\.(?:css|js))"', rf'\1\2?v={VERSION}"', html)
    if "--fragment" in sys.argv:
        html = re.sub(r"<!doctype html>\s*|</?html[^>]*>\s*|</?head>\s*|</?body[^>]*>\s*", "", html, flags=re.I)
        html = re.sub(r'<meta charset="utf-8">\s*<meta name="viewport"[^>]*>\s*', "", html)
    dst.write_text(html)


# the replay app: same files, sign-up links point at the source when there is no server
CONFIG = '<script src="{up}config.js"></script>\n<script type="importmap">'


def with_config(up):
    return lambda h: h.replace('<script type="importmap">', CONFIG.format(up=up), 1)


page(root / "dashboard" / "index.html", app_dir / "index.html", None if app_only else with_config("../"))
def versioned_js(src: Path, dst: Path):
    """Copy a module, pinning its relative imports to this build so browsers never mix versions."""
    js = src.read_text()
    js = re.sub(r'(from\s+"\./[\w/.-]+?\.js)"', rf'\1?v={VERSION}"', js)
    js = re.sub(r'(import\(\s*"\./[\w/.-]+?\.js)"', rf'\1?v={VERSION}"', js)
    js = js.replace('scene.js`)', f'scene.js?v={VERSION}`)')
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(js)


for f in ("app.js", "client.js", "scene.js"):
    versioned_js(root / "dashboard" / f, app_dir / f)
for f in sorted((root / "dashboard" / "engine").glob("*.js")):
    versioned_js(f, app_dir / "engine" / f.name)
for f in ("style.css", "replay.json"):
    shutil.copy(root / "dashboard" / f, app_dir / f)
if not app_only:
    sub = with_config("")
    page(root / "site" / "index.html", out / "index.html", lambda h: sub(h.replace('data-app=""', 'data-app="app/"')))
    for name in ("login.html", "signup.html"):
        page(root / "site" / name, out / name,
             lambda h: h.replace('<link rel="stylesheet" href="site.css">', '<link rel="stylesheet" href="site.css">\n<script src="config.js"></script>'))
    for f in ("site.css", "seasons.json", "favicon.svg"):
        shutil.copy(root / "site" / f, out / f)
    for f in ("site.js", "hero.js"):
        versioned_js(root / "site" / f, out / f)
    versioned_js(root / "dashboard" / "client.js", out / "client.js")
    cfg = out / "config.js"
    if not cfg.exists():          # keep a hand-edited server address
        shutil.copy(root / "site" / "config.js", cfg)
print(out)
