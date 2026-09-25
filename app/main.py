"""
spencerlab.tech — the tech hub.

A small, self-hosted FastAPI blog/vlog over a flat-file journal of technical work, served
publicly through the Cloudflare Tunnel on UbuntuServ. Entries live on disk under
content/entries/<slug>/ (meta.json + body.html + any media) and are loaded at startup.

POST /api/publish lets AuditForge and Fieldnote push finalized, sanitized documents
straight in; see the README for the request shape and its three guards.
"""
from __future__ import annotations

import hmac
import json
import math
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.content import (CAT_BY_SLUG, CATEGORIES, MEDIA_TYPES, extract_inline_images,
                         load_entries, media_path, search)
from app.security import scan_secrets

ROOT = Path(__file__).resolve().parent.parent
CONTENT = Path(os.environ.get("HUB_CONTENT_DIR") or ROOT / "content" / "entries")
BASE_URL = os.environ.get("HUB_BASE_URL", "https://spencerlab.tech").rstrip("/")
PER_PAGE = 9

_ENTRIES: list[dict] = []


def reload_entries() -> None:
    global _ENTRIES
    _ENTRIES = load_entries(CONTENT)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    reload_entries()
    yield


app = FastAPI(title="spencerlab.tech", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.globals["year"] = date.today().year
templates.env.globals["base_url"] = BASE_URL


def _pretty_date(value: str) -> str:
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError):
        return value or ""
    return f"{d:%b} {d.day}, {d.year}"


templates.env.filters["pretty_date"] = _pretty_date


def _topics() -> list[dict]:
    return [dict(c, count=sum(e["category"] == c["slug"] for e in _ENTRIES)) for c in CATEGORIES]


def _render(request: Request, name: str, ctx: dict, status_code: int = 200) -> HTMLResponse:
    ctx.setdefault("topics", _topics())
    ctx.setdefault("nav", None)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _paginate(items: list[dict], page: int) -> tuple[list[dict], dict]:
    pages = max(1, math.ceil(len(items) / PER_PAGE))
    if page < 1 or page > pages:
        raise HTTPException(404)
    start = (page - 1) * PER_PAGE
    return items[start:start + PER_PAGE], {"page": page, "pages": pages, "total": len(items)}


def _listing(request: Request, items: list[dict], page: int, **ctx) -> HTMLResponse:
    shown, pager = _paginate(items, page)
    return _render(request, "list.html", {"entries": shown, "pager": pager, **ctx})


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith(("/api/", "/media/", "/static/")):
        return _render(request, "404.html", {"recent": _ENTRIES[:3]}, status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# --- Pages -----------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    posts = [e for e in _ENTRIES if e["type"] == "post"]
    return _render(request, "home.html", {
        "featured": _ENTRIES[0] if _ENTRIES else None,
        "latest": _ENTRIES[1:7],
        "videos": [e for e in _ENTRIES if e["type"] == "video"][:3],
        "total_posts": len(posts), "total": len(_ENTRIES),
    })


@app.get("/posts", response_class=HTMLResponse)
def all_posts(request: Request, page: int = 1):
    return _listing(request, _ENTRIES, page, nav="posts", kicker="Archive",
                    heading="All posts", intro="Every write-up and video, newest first.",
                    base="/posts")


@app.get("/videos", response_class=HTMLResponse)
def videos(request: Request, page: int = 1):
    vids = [e for e in _ENTRIES if e["type"] == "video"]
    return _listing(request, vids, page, nav="videos", kicker="Vlog", heading="Videos",
                    intro="Build logs and walkthroughs on camera — recorded in the lab, hosted here.",
                    base="/videos",
                    empty="No videos yet. The first build log is being recorded.")


@app.get("/topics", response_class=HTMLResponse)
def topics(request: Request):
    return _render(request, "topics.html", {"nav": "topics"})


@app.get("/tags/{tag}", response_class=HTMLResponse)
def by_tag(request: Request, tag: str, page: int = 1):
    tagged = [e for e in _ENTRIES if tag.lower() in (t.lower() for t in e["tags"])]
    if not tagged:
        raise HTTPException(404)
    return _listing(request, tagged, page, kicker="Tag", heading=f"#{tag}",
                    intro=f"{len(tagged)} post{'s' if len(tagged) != 1 else ''} tagged {tag}.",
                    base=f"/tags/{tag}")


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = ""):
    q = q.strip()[:120]
    results = search(_ENTRIES, q) if q else []
    return _render(request, "search.html", {"q": q, "results": results})


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return _render(request, "about.html", {"nav": "about", "total": len(_ENTRIES)})


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok", "entries": len(_ENTRIES)})


@app.get("/media/{slug}/{name}")
def media(slug: str, name: str):
    f = media_path(CONTENT, slug, name)
    if not f:
        raise HTTPException(404)
    return FileResponse(f, media_type=MEDIA_TYPES[f.suffix.lower()],
                        headers={"Cache-Control": "public, max-age=604800"})


# --- Feeds -----------------------------------------------------------------------

def _rfc822(d: str) -> str:
    try:
        dt = datetime.combine(date.fromisoformat(d), datetime.min.time(), timezone.utc)
    except (TypeError, ValueError):
        dt = datetime.now(timezone.utc)
    return format_datetime(dt)


@app.get("/feed.xml")
def feed(request: Request):
    body = templates.get_template("feed.xml").render(
        entries=_ENTRIES[:30], base=BASE_URL, rfc822=_rfc822,
        built=_rfc822(_ENTRIES[0]["date"]) if _ENTRIES else _rfc822(""))
    return Response(body, media_type="application/rss+xml")


@app.get("/sitemap.xml")
def sitemap():
    urls = ["/", "/posts", "/videos", "/topics", "/about"]
    urls += [f"/{c['slug']}" for c in CATEGORIES] + [e["url"] for e in _ENTRIES]
    xml = "".join(f"<url><loc>{BASE_URL}{u}</loc></url>" for u in urls)
    return Response('<?xml version="1.0" encoding="UTF-8"?>'
                    f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{xml}</urlset>',
                    media_type="application/xml")


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nDisallow: /api/\nSitemap: {BASE_URL}/sitemap.xml\n"


# --- Topic + post pages (catch-all shapes, so they come after the fixed routes) ----

@app.get("/{cat}", response_class=HTMLResponse)
def category(request: Request, cat: str, page: int = 1):
    if cat not in CAT_BY_SLUG:
        raise HTTPException(404)
    c = CAT_BY_SLUG[cat]
    return _listing(request, [e for e in _ENTRIES if e["category"] == cat], page,
                    nav="topics", kicker="Topic", heading=c["name"], intro=c["blurb"],
                    base=f"/{cat}", current_cat=cat,
                    empty=f"Nothing in {c['name']} yet — it lands here when it's written up.")


@app.get("/{cat}/{slug}", response_class=HTMLResponse)
def entry(request: Request, cat: str, slug: str):
    idx = next((i for i, e in enumerate(_ENTRIES)
                if e["slug"] == slug and e["category"] == cat), None)
    if idx is None:
        raise HTTPException(404)
    post = _ENTRIES[idx]
    related = [e for e in _ENTRIES if e is not post and
               (e["category"] == cat or set(e["tags"]) & set(post["tags"]))][:3]
    return _render(request, "post.html", {
        "entry": post, "nav": "posts", "related": related,
        "newer": _ENTRIES[idx - 1] if idx > 0 else None,
        "older": _ENTRIES[idx + 1] if idx + 1 < len(_ENTRIES) else None,
        "canonical": f"{BASE_URL}{post['url']}",
    })


# --- The publish pipeline ----------------------------------------------------------
_SLUG_OK = re.compile(r"[^a-z0-9]+")
_SOURCES = {"auditforge", "fieldnote", "hand"}


def _safe_slug(text: str) -> str:
    s = _SLUG_OK.sub("-", (text or "").lower()).strip("-")[:80]
    if not s or s in {".", ".."}:
        raise HTTPException(422, "could not derive a safe slug from the title")
    return s


def _write_entry(meta: dict, body_html: str, files: dict[str, bytes]) -> None:
    d = CONTENT / meta["slug"]
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (d / name).write_bytes(data)
    (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / "body.html").write_text(body_html, encoding="utf-8")


@app.post("/api/publish")
def publish(payload: dict = Body(...), authorization: str = Header(default="")):
    """Receive a finalized, sanitized entry from AuditForge / Fieldnote (or by hand).

    Guarded three ways: a bearer token, an explicit clearance flag the source tool sets
    only after ITS own sensitivity gate passes, and an automated secret scan as a backstop.
    Disabled entirely unless HUB_PUBLISH_TOKEN is set — no token, no endpoint.
    An existing slug is only overwritten when the caller sends "replace": true.
    """
    token = os.environ.get("HUB_PUBLISH_TOKEN")
    if not token:
        raise HTTPException(503, "publish is disabled (HUB_PUBLISH_TOKEN is not set)")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "missing or invalid bearer token")

    for field in ("title", "category", "summary", "body_html", "source"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise HTTPException(422, f"missing required field: {field}")
    if payload["category"] not in CAT_BY_SLUG:
        raise HTTPException(422, f"unknown category {payload['category']!r}")
    if payload["source"] not in _SOURCES:
        raise HTTPException(422, f"source must be one of {sorted(_SOURCES)}")
    if not isinstance(payload.get("tags", []), list):
        raise HTTPException(422, "tags must be a list")
    if payload.get("date"):
        try:
            date.fromisoformat(str(payload["date"]))
        except ValueError:
            raise HTTPException(422, "date must be YYYY-MM-DD") from None

    # The gate: the source tool must assert its own sensitivity review passed.
    if payload.get("cleared_for_publication") is not True:
        raise HTTPException(
            422,
            "cleared_for_publication must be true — the source tool's sensitivity gate "
            "(AuditForge classification=public/lab; Fieldnote no open secret_findings) must "
            "clear the document before it can be published.",
        )

    slug = _safe_slug(payload.get("slug") or payload["title"])
    if (CONTENT / slug).exists() and payload.get("replace") is not True:
        raise HTTPException(409, f"an entry with slug {slug!r} already exists; "
                                 "send \"replace\": true to overwrite it")

    # Inline data: images become files, so the page stays light and the scan sees text.
    body_html, files = extract_inline_images(slug, payload["body_html"])

    # Automated backstop. Reports the KIND of match, never the value.
    hits = scan_secrets(payload["title"], payload["summary"], body_html)
    if hits:
        raise HTTPException(422, {"refused": "possible secret or sensitive content", "matched": hits})

    meta = {
        "slug": slug,
        "title": payload["title"],
        "category": payload["category"],
        "date": str(payload.get("date") or date.today().isoformat()),
        "summary": payload["summary"],
        "tags": [str(t) for t in payload.get("tags", [])][:12],
        "source": payload["source"],
    }
    _write_entry(meta, body_html, files)
    reload_entries()
    return JSONResponse(
        {"status": "published", "url": f"/{meta['category']}/{slug}", "slug": slug},
        status_code=201,
    )
