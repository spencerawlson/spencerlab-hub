"""
spencerlab.tech — the tech hub.

A small, self-hosted FastAPI site that renders a flat-file journal of technical work,
served publicly through the Cloudflare Tunnel on UbuntuServ. Entries live on disk under
content/entries/<slug>/ as meta.json + body.html and are loaded at startup.

Phase 2 will add POST /api/publish so AuditForge and Fieldnote can push finalized,
sanitized documents straight in. For now this is the read side.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
from datetime import date
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.security import scan_secrets

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content" / "entries"

# The five disciplines. Order is the story: build it, fix it, break into it, judge it, run it.
CATEGORIES = [
    {"slug": "built",        "name": "Built",        "short": "Built",
     "blurb": "Infrastructure and systems stood up from scratch — servers, networks, sites, tooling."},
    {"slug": "repaired",     "name": "Repaired",     "short": "Repaired",
     "blurb": "Things that broke, and how they were diagnosed and put back — with the dead ends kept in."},
    {"slug": "pentested",    "name": "Pentested",    "short": "Pentested",
     "blurb": "Offensive security on lab targets and authorized scope — methodology, tooling, and findings."},
    {"slug": "assessed",     "name": "Assessed",     "short": "Assessed",
     "blurb": "Posture reviews, audits, and risk assessments — what was measured and what it meant."},
    {"slug": "administered", "name": "Administered", "short": "Admin",
     "blurb": "The day-to-day of running systems — users, services, backups, monitoring, upkeep."},
]
CAT_BY_SLUG = {c["slug"]: c for c in CATEGORIES}
for i, c in enumerate(CATEGORIES, 1):
    c["n"] = f"0{i}"

def _build_globe_dots() -> str:
    """Pre-render the hero globe's point cloud as SVG <circle> markup (computed once).

    A tilted Fibonacci sphere projected orthographically: dots are depth-shaded so the
    near hemisphere reads bright and the far one recedes, with a few 'hot' nodes haloed.
    """
    rnd = random.Random(7)
    n, cx, cy, r = 156, 160, 150, 104
    tilt = math.radians(17)
    ca, sa = math.cos(tilt), math.sin(tilt)
    pts = []
    for i in range(n):
        y = 1 - (i + 0.5) * 2.0 / n
        rr = math.sqrt(max(0.0, 1 - y * y))
        theta = math.pi * (1 + 5 ** 0.5) * i
        x = math.cos(theta) * rr
        z = math.sin(theta) * rr
        y2 = y * ca - z * sa
        z2 = y * sa + z * ca
        pts.append((z2, cx + x * r, cy - y2 * r, x))
    pts.sort(key=lambda p: p[0])
    hot = set(rnd.sample(range(len(pts)), 7))
    out = []
    for idx, (z2, sx, sy, x) in enumerate(pts):
        front = z2 > 0
        d = (z2 + 1) / 2
        if idx in hot and front:
            out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="2.6" fill="#dafff0"/>')
            out.append(f'<circle class="tw" cx="{sx:.1f}" cy="{sy:.1f}" r="5.0" fill="none" '
                       f'stroke="#8ff5d0" stroke-width="0.8" opacity="0.5"/>')
        elif front:
            col = "#3fe0b0" if x > 0 else "#2ec89a"
            out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{1.4 + d * 1.1:.2f}" '
                       f'fill="{col}" opacity="{0.5 + d * 0.5:.2f}"/>')
        else:
            out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{0.7 + d * 0.5:.2f}" '
                       f'fill="#1f7a5e" opacity="{0.10 + d * 0.22:.2f}"/>')
    return "\n".join(out)


GLOBE_DOTS = _build_globe_dots()

app = FastAPI(title="spencerlab.tech", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

_ENTRIES: list[dict] = []


def load_entries() -> list[dict]:
    """Read every content/entries/<slug>/ (meta.json + body.html), newest first."""
    items: list[dict] = []
    if not CONTENT.exists():
        return items
    for d in sorted(CONTENT.iterdir()):
        meta_f, body_f = d / "meta.json", d / "body.html"
        if not (meta_f.exists() and body_f.exists()):
            continue
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        cat = meta.get("category")
        if cat not in CAT_BY_SLUG:
            # An entry with an unknown category is a mistake worth seeing, not hiding.
            raise ValueError(f"{d.name}: unknown category {cat!r}")
        meta["slug"] = meta.get("slug", d.name)
        meta["category_name"] = CAT_BY_SLUG[cat]["name"]
        meta["body"] = body_f.read_text(encoding="utf-8")
        meta.setdefault("tags", [])
        items.append(meta)
    items.sort(key=lambda m: (m.get("date", ""), m.get("slug", "")), reverse=True)
    return items


@app.on_event("startup")
def _startup() -> None:
    global _ENTRIES
    _ENTRIES = load_entries()


def _counts() -> list[dict]:
    out = []
    for c in CATEGORIES:
        c = dict(c)
        c["count"] = sum(1 for e in _ENTRIES if e["category"] == c["slug"])
        out.append(c)
    return out


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    cats = _counts()
    featured = _ENTRIES[0] if _ENTRIES else None
    recent = _ENTRIES[1:7]
    return templates.TemplateResponse(request, "home.html", {
        "categories": cats, "current_cat": None,
        "featured": featured, "recent": recent, "total_entries": len(_ENTRIES),
        "globe_dots": GLOBE_DOTS,
    })


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok", "entries": len(_ENTRIES)})


@app.get("/{cat}", response_class=HTMLResponse)
def category(request: Request, cat: str):
    if cat not in CAT_BY_SLUG:
        raise HTTPException(404)
    entries = [e for e in _ENTRIES if e["category"] == cat]
    return templates.TemplateResponse(request, "category.html", {
        "categories": _counts(), "current_cat": cat,
        "category": CAT_BY_SLUG[cat], "entries": entries,
    })


@app.get("/{cat}/{slug}", response_class=HTMLResponse)
def entry(request: Request, cat: str, slug: str):
    if cat not in CAT_BY_SLUG:
        raise HTTPException(404)
    match = next((e for e in _ENTRIES if e["slug"] == slug and e["category"] == cat), None)
    if not match:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "entry.html", {
        "categories": _counts(), "current_cat": cat, "entry": match,
    })


# --- Phase 2: the publish pipeline ----------------------------------------------
_SLUG_OK = re.compile(r"[^a-z0-9]+")
_SOURCES = {"auditforge", "fieldnote", "hand"}


def _safe_slug(text: str) -> str:
    s = _SLUG_OK.sub("-", (text or "").lower()).strip("-")[:80]
    if not s or s in {".", ".."}:
        raise HTTPException(422, "could not derive a safe slug from the title")
    return s


def _write_entry(meta: dict, body_html: str) -> None:
    d = CONTENT / meta["slug"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / "body.html").write_text(body_html, encoding="utf-8")


@app.post("/api/publish")
def publish(payload: dict = Body(...), authorization: str = Header(default="")):
    """Receive a finalized, sanitized entry from AuditForge / Fieldnote (or by hand).

    Guarded three ways: a bearer token, an explicit clearance flag the source tool sets
    only after ITS own sensitivity gate passes, and an automated secret scan as a backstop.
    Disabled entirely unless HUB_PUBLISH_TOKEN is set — no token, no endpoint.
    """
    global _ENTRIES
    token = os.environ.get("HUB_PUBLISH_TOKEN")
    if not token:
        raise HTTPException(503, "publish is disabled (HUB_PUBLISH_TOKEN is not set)")
    if authorization != f"Bearer {token}":
        raise HTTPException(401, "missing or invalid bearer token")

    for field in ("title", "category", "summary", "body_html", "source"):
        if not payload.get(field):
            raise HTTPException(422, f"missing required field: {field}")
    if payload["category"] not in CAT_BY_SLUG:
        raise HTTPException(422, f"unknown category {payload['category']!r}")
    if payload["source"] not in _SOURCES:
        raise HTTPException(422, f"source must be one of {sorted(_SOURCES)}")

    # The gate: the source tool must assert its own sensitivity review passed.
    if payload.get("cleared_for_publication") is not True:
        raise HTTPException(
            422,
            "cleared_for_publication must be true — the source tool's sensitivity gate "
            "(AuditForge classification=public/lab; Fieldnote no open secret_findings) must "
            "clear the document before it can be published.",
        )

    # Automated backstop. Reports the KIND of match, never the value.
    hits = scan_secrets(payload["title"], payload["summary"], payload["body_html"])
    if hits:
        raise HTTPException(422, {"refused": "possible secret or sensitive content", "matched": hits})

    slug = _safe_slug(payload.get("slug") or payload["title"])
    meta = {
        "slug": slug,
        "title": payload["title"],
        "category": payload["category"],
        "date": payload.get("date") or date.today().isoformat(),
        "summary": payload["summary"],
        "tags": [str(t) for t in payload.get("tags", [])][:12],
        "source": payload["source"],
    }
    _write_entry(meta, payload["body_html"])
    _ENTRIES = load_entries()
    return JSONResponse(
        {"status": "published", "url": f"/{meta['category']}/{slug}", "slug": slug},
        status_code=201,
    )
