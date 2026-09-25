import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.content import load_entries

REAL_CONTENT = Path(__file__).resolve().parent.parent / "content" / "entries"
TOKEN = "test-token-0123456789"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def _entry(root: Path, slug: str, body: str, files: dict[str, bytes] | None = None, **meta):
    d = root / slug
    d.mkdir(parents=True)
    meta = {"title": slug.replace("-", " ").title(), "category": "built",
            "date": "2026-09-01", "summary": f"Summary of {slug}.", "tags": [], **meta}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "body.html").write_text(body, encoding="utf-8")
    for name, data in (files or {}).items():
        (d / name).write_bytes(data)


@pytest.fixture
def client(tmp_path, monkeypatch):
    _entry(tmp_path, "tunnel-post",
           '<header class="masthead"><div class="readwrap"><h1 class="title">X</h1>'
           '<div class="byline"><span><b>Ref</b> RPT-1</span></div></div></header>'
           '<div class="readwrap"><section><h2>One</h2><p>alpha nmap</p></section>'
           '<section><h2>Two</h2></section><section><h2>Two</h2></section></div>',
           tags=["cloudflare", "dns"], date="2026-09-05")
    _entry(tmp_path, "cyberdeck-video", "<p>Notes under the video.</p>",
           files={"video.mp4": b"0123456789" * 100, "poster.jpg": b"jpg"},
           video="video.mp4", poster="poster.jpg", duration="12:04", date="2026-09-06")
    _entry(tmp_path, "winserv-report", "<p>WinRM finding.</p>", category="assessed", tags=["dns"])
    monkeypatch.setattr(main, "CONTENT", tmp_path)
    monkeypatch.setenv("HUB_PUBLISH_TOKEN", TOKEN)
    with TestClient(main.app) as c:
        yield c


def _publish(client, token=TOKEN, **overrides):
    payload = {"title": "Nmap recon on the lab", "category": "pentested", "summary": "Recon.",
               "body_html": "<section><p>Scan results.</p></section>", "source": "fieldnote",
               "cleared_for_publication": True, **overrides}
    return client.post("/api/publish", json=payload, headers={"Authorization": f"Bearer {token}"})


# --- the real content folder --------------------------------------------------------

def test_real_content_loads_and_is_light():
    entries = load_entries(REAL_CONTENT)
    assert entries, "expected published entries"
    for e in entries:
        assert e["summary"] and not e["summary"].endswith(" b"), e["slug"]
        assert "data:image" not in e["body"], f"{e['slug']} still inlines images"
        assert len(e["body"]) < 500_000, f"{e['slug']} body is too heavy"


# --- pages ------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/posts", "/videos", "/topics", "/about", "/built",
                                  "/assessed", "/tags/dns", "/search?q=nmap", "/search"])
def test_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_home_features_newest(client):
    html = client.get("/").text
    assert html.index("Cyberdeck Video") < html.index("Tunnel Post")


def test_post_page_strips_masthead_keeps_byline_and_builds_toc(client):
    html = client.get("/built/tunnel-post").text
    assert 'class="masthead"' not in html
    assert "RPT-1" in html
    assert 'id="one"' in html and 'id="two"' in html and 'id="two-2"' in html
    assert 'href="#two-2"' in html


def test_video_post_renders_player_and_media_supports_range(client):
    html = client.get("/built/cyberdeck-video").text
    assert "<video" in html and "/media/cyberdeck-video/video.mp4" in html
    r = client.get("/media/cyberdeck-video/video.mp4", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == b"0123456789"
    assert client.get("/videos").text.count('class="card"') == 1


@pytest.mark.parametrize("name", ["meta.json", "body.html", "..%2Fmeta.json", "nope.mp4"])
def test_media_refuses_non_media(client, name):
    assert client.get(f"/media/cyberdeck-video/{name}").status_code == 404


def test_search_filters_and_misses(client):
    assert "Tunnel Post" in client.get("/search?q=nmap").text
    assert "Tunnel Post" not in client.get("/search?q=kerberos").text


def test_unknown_pages_404_with_page(client):
    for path in ["/nope", "/built/nope", "/tags/nope", "/posts?page=9"]:
        r = client.get(path)
        assert r.status_code == 404 and "doesn't exist" in r.text


def test_feeds(client):
    rss = client.get("/feed.xml")
    assert rss.status_code == 200 and "<item>" in rss.text and "/built/tunnel-post" in rss.text
    assert "/assessed/winserv-report" in client.get("/sitemap.xml").text
    assert "Sitemap:" in client.get("/robots.txt").text


# --- publish API --------------------------------------------------------------------

def test_publish_requires_token(client, monkeypatch):
    assert _publish(client, token="wrong").status_code == 401
    monkeypatch.delenv("HUB_PUBLISH_TOKEN")
    assert _publish(client).status_code == 503


def test_publish_creates_and_refuses_silent_overwrite(client):
    r = _publish(client)
    assert r.status_code == 201 and r.json()["url"] == "/pentested/nmap-recon-on-the-lab"
    assert client.get("/pentested/nmap-recon-on-the-lab").status_code == 200

    assert _publish(client, summary="Changed.").status_code == 409
    assert _publish(client, summary="Changed.", replace=True).status_code == 201
    assert "Changed." in client.get("/pentested/nmap-recon-on-the-lab").text


def test_publish_extracts_inline_images(client):
    body = f'<figure><img src="data:image/png;base64,{PNG}"></figure>' * 2
    assert _publish(client, body_html=body).status_code == 201
    d = main.CONTENT / "nmap-recon-on-the-lab"
    images = list(d.glob("img-*.png"))
    assert len(images) == 1  # identical images are stored once
    assert "data:image" not in (d / "body.html").read_text(encoding="utf-8")
    assert client.get(f"/media/nmap-recon-on-the-lab/{images[0].name}").status_code == 200


@pytest.mark.parametrize("overrides", [
    {"cleared_for_publication": False},
    {"category": "hacked"},
    {"source": "email"},
    {"date": "yesterday"},
    {"tags": "not-a-list"},
    {"body_html": "aws_secret_access_key = x"},
])
def test_publish_rejects_bad_payloads(client, overrides):
    assert _publish(client, **overrides).status_code == 422
