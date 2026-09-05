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
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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


# --- Phase 2 seam (not wired yet) ------------------------------------------------
# POST /api/publish will accept a finalized, sanitized document from AuditForge /
# Fieldnote: {title, category, slug, date, tags, summary, html, attachments[]},
# token-authenticated, and only after the source tool's own sensitivity gate has
# cleared it (AuditForge classification=public/lab; Fieldnote no open secret_findings).
# Intentionally absent until that gate is built — a publish endpoint without it would
# be the exact hole this hub is meant not to have.
