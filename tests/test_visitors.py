import sqlite3
from datetime import datetime, timedelta, timezone

from app import main
from app.visitors import Visitors, parse_ua
from test_app import STATS_TOKEN, client  # noqa: F401  (client is a fixture)

CHROME_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
SAFARI_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                 "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
CF = {"CF-Connecting-IP": "203.0.113.7", "CF-IPCountry": "GB", "cf-ipcity": "Leeds",
      "cf-region": "England", "cf-timezone": "Europe/London", "User-Agent": CHROME_WIN}


def _stats(client, token=STATS_TOKEN, **params):
    return client.get("/api/visitors", params=params, headers={"Authorization": f"Bearer {token}"})


def _rows():
    if not main.VISITS.db.exists():
        return []
    con = sqlite3.connect(main.VISITS.db)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM visits ORDER BY id")]
    finally:
        con.close()


def test_page_view_records_ip_location_and_device(client):
    client.get("/built/tunnel-post?utm_source=linkedin",
               headers={**CF, "Referer": "https://www.linkedin.com/feed/"})
    (row,) = _rows()
    assert row["path"] == "/built/tunnel-post" and row["status"] == 200
    assert row["ip"] == "203.0.113.7"
    assert (row["country"], row["region"], row["city"], row["timezone"]) == ("GB", "England", "Leeds", "Europe/London")
    assert (row["browser"], row["os"], row["device"], row["bot"]) == ("Chrome", "Windows", "Desktop", 0)
    assert row["ref_host"] == "www.linkedin.com" and row["utm_source"] == "linkedin"
    assert row["visitor"] and "203.0.113.7" not in row["visitor"]


def test_non_pages_are_not_recorded(client):
    for path in ("/static/site.css", "/api/lab", "/healthz", "/feed.xml", "/media/cyberdeck-video/poster.jpg"):
        client.get(path, headers=CF)
    client.get("/", headers={**CF, "Sec-Purpose": "prefetch"})
    assert _rows() == []


def test_internal_navigation_is_not_a_referrer_and_404s_count(client):
    client.get("/posts", headers={**CF, "Referer": "https://spencerlab.tech/"})
    client.get("/no-such-page", headers=CF)
    rows = _rows()
    assert rows[0]["ref_host"] is None
    assert rows[1]["status"] == 404


def test_proxy_headers_ignored_from_untrusted_client(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "VISITS", Visitors(tmp_path / "_untrusted", "spencerlab.tech",
                                                 trusted_proxies={"127.0.0.1"}))
    client.get("/", headers=CF)
    (row,) = _rows()
    assert row["ip"] == "testclient" and row["country"] is None and row["city"] is None


def test_stats_endpoint_is_token_gated_and_summarises(client, monkeypatch):
    client.get("/", headers=CF)
    client.get("/posts", headers=CF)                                    # same visitor
    client.get("/", headers={**CF, "CF-Connecting-IP": "198.51.100.2", "CF-IPCountry": "US",
                             "cf-ipcity": "Austin", "cf-region": "Texas", "User-Agent": SAFARI_IPHONE})
    client.get("/", headers={**CF, "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"})

    assert client.get("/api/visitors").status_code == 401
    assert _stats(client, token="wrong").status_code == 401
    d = _stats(client).json()
    assert (d["views"], d["visitors"], d["bot_views"]) == (3, 2, 1)
    assert {c["k"]: c["views"] for c in d["countries"]} == {"GB": 2, "US": 1}
    assert "Austin, Texas, US" in {c["k"] for c in d["cities"]}
    assert {x["k"] for x in d["devices"]} == {"Desktop", "Mobile"}
    assert len(d["recent"]) == 4 and d["recent"][0]["bot"] == 1

    monkeypatch.delenv("HUB_STATS_TOKEN")
    assert _stats(client).status_code == 503


def test_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("HUB_VISITS_DISABLED", "1")
    client.get("/", headers=CF)
    assert not main.VISITS.db.exists() or _rows() == []


def test_retention_purges_old_rows(tmp_path):
    v = Visitors(tmp_path)
    v.record(path="/", query="", status=200, client_host="127.0.0.1", headers={"user-agent": CHROME_WIN})
    old = (datetime.now(timezone.utc) - timedelta(days=v.retain_days + 1)).isoformat(timespec="seconds")
    con = sqlite3.connect(v.db)
    con.execute("UPDATE visits SET at = ?", (old,))
    con.commit()
    con.close()
    assert v.purge() == 1


def test_parse_ua():
    assert parse_ua(SAFARI_IPHONE) == {"browser": "Safari", "os": "iOS", "device": "Mobile", "bot": False}
    assert parse_ua("curl/8.4.0")["bot"] is True
    assert parse_ua("")["device"] == "Bot"


def test_map_points_use_city_coordinates_else_country_centre(client):
    client.get("/", headers={**CF, "cf-iplatitude": "53.80", "cf-iplongitude": "-1.55"})
    client.get("/posts", headers={**CF, "cf-iplatitude": "53.80", "cf-iplongitude": "-1.55"})
    client.get("/", headers={"CF-Connecting-IP": "198.51.100.9", "CF-IPCountry": "JP", "User-Agent": CHROME_WIN})
    client.get("/", headers={**CF, "CF-Connecting-IP": "198.51.100.10", "CF-IPCountry": "T1"})   # Tor: unplaceable
    pts = {p["label"]: p for p in _stats(client).json()["points"]}
    assert set(pts) == {"Leeds, England, United Kingdom", "Japan"}
    leeds, japan = pts["Leeds, England, United Kingdom"], pts["Japan"]
    assert (leeds["level"], leeds["lat"], leeds["lon"], leeds["views"], leeds["visitors"]) == ("city", 53.8, -1.55, 2, 1)
    assert japan["level"] == "country" and japan["views"] == 1 and abs(japan["lat"] - 36.2) < 1


def test_stats_page_is_a_shell_that_is_never_logged_or_indexed(client):
    client.get("/", headers=CF)                       # one real view with a known IP
    html = client.get("/stats", headers=CF).text
    assert 'name="robots" content="noindex' in html and "data-gate" in html and "wm-land" in html
    assert "203.0.113.7" not in html                  # no data in the HTML; it loads with the token
    assert [r["path"] for r in _rows()] == ["/"]
    assert "Disallow: /stats" in client.get("/robots.txt").text


def test_about_page_discloses_the_visit_log_and_its_retention(client, monkeypatch):
    html = client.get("/about").text
    assert 'id="privacy"' in html and "No cookies" in html and f"after {main.VISITS.retain_days} days" in html
    monkeypatch.setenv("HUB_VISITS_DISABLED", "1")
    assert "Visit logging is switched off" in client.get("/about").text


def test_purge_does_not_create_a_database(tmp_path):
    v = Visitors(tmp_path)
    assert v.purge() == 0 and not v.db.exists()


def test_terminal_report(tmp_path):
    from app.visitors import _report
    v = Visitors(tmp_path)
    v.record(path="/posts", query="", status=200, client_host="127.0.0.1",
             headers={"cf-connecting-ip": "203.0.113.7", "cf-ipcountry": "GB", "cf-ipcity": "Leeds", "user-agent": CHROME_WIN})
    text = _report(v.summary(days=7))
    assert "views 1   unique visitors 1" in text and "United Kingdom" in text
    assert "Leeds, GB" in text and "/posts" in text and "203.0.113.7" in text


def _live(client, since=None, token=STATS_TOKEN):
    q = "" if since is None else f"?since={since}"
    return client.get(f"/api/visitors/live{q}", headers={"Authorization": f"Bearer {token}"})


def test_live_feed_starts_from_now_then_returns_only_new_visits(client):
    client.get("/", headers=CF)                                          # history, before watching
    assert client.get("/api/visitors/live").status_code == 401
    first = _live(client).json()
    assert first["visits"] == [] and first["last_id"] == 1 and first["active_now"] == 1

    client.get("/posts", headers={**CF, "cf-iplatitude": "53.80", "cf-iplongitude": "-1.55"})
    client.get("/", headers={"CF-Connecting-IP": "198.51.100.9", "CF-IPCountry": "JP", "User-Agent": SAFARI_IPHONE})
    client.get("/", headers={**CF, "User-Agent": "Googlebot/2.1"})
    d = _live(client, first["last_id"]).json()
    assert [v["path"] for v in d["visits"]] == ["/posts", "/", "/"]
    leeds, japan, bot = d["visits"]
    assert leeds["point"]["level"] == "city" and leeds["point"]["lat"] == 53.8
    assert japan["point"] == {"lat": japan["point"]["lat"], "lon": japan["point"]["lon"], "level": "country",
                              "country": "JP", "label": "Japan"}
    assert bot["bot"] == 1
    assert d["active_now"] == 2 and d["last_id"] == 4                    # GB + JP humans; the bot doesn't count
    assert {a["country"] for a in d["active"]} == {"GB", "JP"} and "visitor" not in d["active"][0]
    assert _live(client, d["last_id"]).json()["visits"] == []            # nothing replayed


def test_live_feed_pages_through_a_burst(tmp_path):
    v = Visitors(tmp_path)
    for i in range(5):
        v.record(path=f"/p{i}", query="", status=200, client_host="127.0.0.1", headers={"user-agent": CHROME_WIN})
    page = v.live(since_id=0, limit=3)
    assert [r["path"] for r in page["visits"]] == ["/p0", "/p1", "/p2"] and page["last_id"] == 3
    assert [r["path"] for r in v.live(since_id=page["last_id"], limit=3)["visits"]] == ["/p3", "/p4"]
