"""
The content layer: turns content/entries/<slug>/ folders into post dicts the templates use.

Each entry folder holds meta.json + body.html, plus any media the post references (images,
a self-hosted video, a poster/cover). Media is served from /media/<slug>/<file>.

Bodies arrive from AuditForge / Fieldnote with their own masthead (<header class="masthead">).
The site renders the post header from meta.json instead, so the masthead is lifted out at load
time — its byline is kept and shown in the post header.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import re
from pathlib import Path

# The five disciplines. Order is the story: build it, fix it, break into it, judge it, run it.
CATEGORIES = [
    {"slug": "built",        "name": "Built",
     "blurb": "Infrastructure and systems stood up from scratch — servers, networks, sites, tooling."},
    {"slug": "repaired",     "name": "Repaired",
     "blurb": "Things that broke, and how they were diagnosed and put back — with the dead ends kept in."},
    {"slug": "pentested",    "name": "Pentested",
     "blurb": "Offensive security on lab targets and authorized scope — methodology, tooling, and findings."},
    {"slug": "assessed",     "name": "Assessed",
     "blurb": "Posture reviews, audits, and risk assessments — what was measured and what it meant."},
    {"slug": "administered", "name": "Administered",
     "blurb": "The day-to-day of running systems — users, services, backups, monitoring, upkeep."},
]
CAT_BY_SLUG = {c["slug"]: c for c in CATEGORIES}

# Files an entry folder may serve publicly. meta.json / body.html are never served raw.
MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".svg": "image/svg+xml", ".avif": "image/avif",
    ".mp4": "video/mp4", ".webm": "video/webm", ".vtt": "text/vtt",
}
_MEDIA_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")

_MASTHEAD = re.compile(r'^\s*<header class="masthead">(.*?)</header>\s*', re.S)
_BYLINE = re.compile(r'<div class="byline">(.*?)</div>', re.S)
_GENERATED = re.compile(r"<span><b>Generated</b>[^<]*</span>")
_H2 = re.compile(r"<h2(\s[^>]*)?>(.*?)</h2>", re.S)
_TAGS = re.compile(r"<[^>]+>")
_WORDS_PER_MIN = 225

_DATA_IMG = re.compile(r'src="data:image/(png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=\s]+)"')


def media_url(slug: str, value: str | None) -> str | None:
    """A meta.json media field is a file in the entry folder, or an absolute URL/path."""
    if not value:
        return None
    if value.startswith(("http://", "https://", "/")):
        return value
    return f"/media/{slug}/{value}"


def media_path(content_dir: Path, slug: str, name: str) -> Path | None:
    """Resolve /media/<slug>/<name> to a file on disk, or None if it is not servable."""
    if not _MEDIA_NAME.match(name) or Path(name).suffix.lower() not in MEDIA_TYPES:
        return None
    entry_dir = (content_dir / slug).resolve()
    f = (entry_dir / name).resolve()
    if f.parent != entry_dir or not f.is_file():
        return None
    return f


def plain_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", fragment))).strip()


def _anchor(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "section"
    a, n = base, 2
    while a in used:
        a, n = f"{base}-{n}", n + 1
    used.add(a)
    return a


def _add_heading_ids(body: str) -> tuple[str, list[dict]]:
    """Give every <h2> an id (keeping any it already has) and return the table of contents."""
    toc: list[dict] = []
    used: set[str] = set()

    def repl(m: re.Match) -> str:
        attrs, inner = m.group(1) or "", m.group(2)
        text = plain_text(inner)
        existing = re.search(r'\bid="([^"]+)"', attrs)
        if existing:
            anchor = existing.group(1)
            used.add(anchor)
        else:
            anchor = _anchor(text, used)
            attrs = f' id="{anchor}"{attrs}'
        toc.append({"id": anchor, "text": text})
        return f"<h2{attrs}>{inner}</h2>"

    return _H2.sub(repl, body), toc


def extract_inline_images(slug: str, body: str) -> tuple[str, dict[str, bytes]]:
    """Pull base64 data: images out of a body into files, identical images stored once.

    Returns the rewritten body (pointing at /media/<slug>/img-<hash>.<ext>) and the
    {filename: bytes} to write. Nothing is written here, so a caller can still refuse.
    """
    files: dict[str, bytes] = {}

    def repl(m: re.Match) -> str:
        ext = "jpg" if m.group(1).startswith("jp") else m.group(1)
        data = base64.b64decode(re.sub(r"\s+", "", m.group(2)))
        name = f"img-{hashlib.sha256(data).hexdigest()[:12]}.{ext}"
        files[name] = data
        return f'src="/media/{slug}/{name}" loading="lazy"'

    return _DATA_IMG.sub(repl, body), files


def build_entry(entry_dir: Path) -> dict | None:
    meta_f, body_f = entry_dir / "meta.json", entry_dir / "body.html"
    if not (meta_f.exists() and body_f.exists()):
        return None
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    cat = meta.get("category")
    if cat not in CAT_BY_SLUG:
        # An entry with an unknown category is a mistake worth seeing, not hiding.
        raise ValueError(f"{entry_dir.name}: unknown category {cat!r}")

    slug = meta.get("slug") or entry_dir.name
    body = body_f.read_text(encoding="utf-8")

    byline = ""
    m = _MASTHEAD.match(body)
    if m:
        b = _BYLINE.search(m.group(1))
        # Fieldnote stamps a raw ISO "Generated" time; the post date already says when.
        byline = _GENERATED.sub("", b.group(1)).strip() if b else ""
        body = body[m.end():]

    body, toc = _add_heading_ids(body)
    text = plain_text(body)
    minutes = max(1, math.ceil(len(text.split()) / _WORDS_PER_MIN))

    meta.update({
        "slug": slug,
        "dir": entry_dir.name,
        "category_name": CAT_BY_SLUG[cat]["name"],
        "url": f"/{cat}/{slug}",
        "body": body,
        "byline": byline,
        "toc": toc if len(toc) >= 3 else [],
        "reading_time": meta.get("reading_time") or f"{minutes} min",
        "search_text": " ".join([meta.get("title", ""), meta.get("summary", ""),
                                 " ".join(meta.get("tags", [])), text]).lower(),
        "cover_url": media_url(entry_dir.name, meta.get("cover")),
        "video_url": media_url(entry_dir.name, meta.get("video")),
        "poster_url": media_url(entry_dir.name, meta.get("poster") or meta.get("cover")),
        "captions_url": media_url(entry_dir.name, meta.get("captions")),
    })
    meta.setdefault("tags", [])
    meta["type"] = "video" if meta["video_url"] else "post"
    return meta


def load_entries(content_dir: Path) -> list[dict]:
    """Read every content/entries/<slug>/, newest first."""
    if not content_dir.exists():
        return []
    items = [e for d in sorted(content_dir.iterdir()) if d.is_dir() and (e := build_entry(d))]
    items.sort(key=lambda e: (e.get("date", ""), e["slug"]), reverse=True)
    return items


def search(entries: list[dict], query: str) -> list[dict]:
    """Every term must appear; title matches rank first, then recency (already sorted)."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    hits = [e for e in entries if all(t in e["search_text"] for t in terms)]
    return sorted(hits, key=lambda e: -sum(t in e["title"].lower() for t in terms))
