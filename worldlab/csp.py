"""Content Security Policy for WorldLab's pages.

The app and the website run only their own scripts, the pinned three.js modules from jsDelivr and, for the inline
import map, exactly the bytes hashed here. They talk to their own origin and the configured WorldLab server, load fonts
from Google Fonts and images from themselves (plus data: and blob: URLs the app creates). Everything else, including
plug-in content, other frames and form posts elsewhere, is refused. This narrows what an injected script could do with
a session token kept in the browser.
"""
import base64
import hashlib
import re

INLINE = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/ld\+json)[^>]*>(.*?)</script>", re.S | re.I)


def policy(html: str, api: str = "") -> str:
    hashes = " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(m.encode()).digest()).decode()}'" for m in INLINE.findall(html))
    connect = " ".join(x for x in ("'self'", api.rstrip("/") if api else "", "https://cdn.jsdelivr.net") if x)
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' https://cdn.jsdelivr.net {hashes}".strip(),
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob:",
        f"connect-src {connect}",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        f"form-action 'self'{(' ' + api.rstrip('/')) if api else ''}",
    ])


def add_meta(html: str, api: str = "") -> str:
    """Put the policy in the page itself (static hosts such as GitHub Pages can't send headers)."""
    tag = f'<meta http-equiv="Content-Security-Policy" content="{policy(html, api)}">'
    return re.sub(r'(<meta charset="utf-8">)', r"\1\n" + tag.replace("\\", "\\\\"), html, count=1, flags=re.I)
