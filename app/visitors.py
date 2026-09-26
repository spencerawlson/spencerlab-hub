"""
Visitor log: who reads the site, and from where.

Every HTML page view is written to a small SQLite database (data/visits.db, not in git):
time, path, the visitor's IP, a stable visitor id (for unique/returning counts), location,
referrer, browser / OS / device and a bot flag. Static files, media, the API and health
checks are not page views and are skipped.

Location comes from Cloudflare, which sits in front of the tunnel:
- CF-Connecting-IP — the real client IP (the app itself only ever sees localhost);
- CF-IPCountry     — ISO country code, on by default ("XX" unknown, "T1" Tor);
- cf-region / cf-ipcity / cf-timezone / cf-iplatitude / cf-iplongitude — only when the
  "Add visitor location headers" Managed Transform is enabled in the Cloudflare dashboard.
These headers are trusted ONLY when the request arrives from a trusted proxy (localhost:
cloudflared or Nginx). Anyone reaching the app another way cannot spoof an IP or a location.

Raw IPs are personal data, so rows older than HUB_VISITS_RETAIN_DAYS (default 90) are purged.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_SKIP_PREFIXES = ("/static/", "/media/", "/api/", "/healthz", "/stats")
_PURGE_EVERY = 500    # records between retention sweeps

# ISO 3166-1 alpha-2 -> [lat, lon, name]: country centroids (Google's public countries
# dataset), so a visit still lands on the map when Cloudflare sends a country but no city.
COUNTRIES: dict[str, list] = json.loads((Path(__file__).with_name("countries.json")).read_text(encoding="utf-8"))

_BOT = re.compile(r"bot|crawl|spider|slurp|scan|curl|wget|python-|httpx|aiohttp|go-http|java/|"
                  r"headless|lighthouse|preview|facebookexternalhit|embedly|monitor|uptime|feed", re.I)
_BROWSERS = [("Edge", r"Edg(e|A|iOS)?/"), ("Opera", r"OPR/|Opera"), ("Samsung Internet", r"SamsungBrowser"),
             ("Firefox", r"Firefox/|FxiOS"), ("Chrome", r"Chrome/|CriOS"), ("Safari", r"Safari/")]
_OSES = [("Windows", r"Windows"), ("Android", r"Android"), ("iOS", r"iPhone|iPad|iPod"),
         ("ChromeOS", r"CrOS"), ("macOS", r"Mac OS X|Macintosh"), ("Linux", r"Linux")]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL, path TEXT NOT NULL, status INTEGER,
  ip TEXT, visitor TEXT,
  country TEXT, region TEXT, city TEXT, timezone TEXT, lat REAL, lon REAL,
  referrer TEXT, ref_host TEXT, utm_source TEXT,
  ua TEXT, browser TEXT, os TEXT, device TEXT, bot INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS visits_at ON visits(at);
"""


def parse_ua(ua: str) -> dict:
    bot = bool(_BOT.search(ua)) or not ua
    browser = next((name for name, pat in _BROWSERS if re.search(pat, ua)), "Other")
    os_name = next((name for name, pat in _OSES if re.search(pat, ua)), "Other")
    if bot:
        device = "Bot"
    elif re.search(r"iPad|Tablet", ua) or (os_name == "Android" and "Mobile" not in ua):
        device = "Tablet"
    elif re.search(r"Mobi|iPhone|iPod", ua):
        device = "Mobile"
    else:
        device = "Desktop"
    return {"browser": browser, "os": os_name, "device": device, "bot": bot}


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v else None
    except ValueError:
        return None


class Visitors:
    def __init__(self, data_dir: Path, site_host: str = "",
                 trusted_proxies: set[str] | None = None):
        self.db = data_dir / "visits.db"
        self.salt_file = data_dir / "visits.salt"
        self.site_host = site_host.lower()
        self.trusted = trusted_proxies if trusted_proxies is not None else {"127.0.0.1", "::1"}
        self.retain_days = int(os.environ.get("HUB_VISITS_RETAIN_DAYS", "90"))
        self._salt: bytes | None = None
        self._since_purge = 0

    # --- storage --------------------------------------------------------------------

    @contextmanager
    def _connect(self):
        """One short-lived connection per operation: commit on success, always close."""
        self.db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db, timeout=5)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.executescript(_SCHEMA)
            yield con
            con.commit()
        finally:
            con.close()

    def _visitor_id(self, ip: str, ua: str) -> str:
        """Stable per IP + browser, so repeat visits count once; not reversible to the IP."""
        if self._salt is None:
            if self.salt_file.exists():
                self._salt = self.salt_file.read_bytes()
            else:
                self._salt = secrets.token_bytes(16)
                self.salt_file.parent.mkdir(parents=True, exist_ok=True)
                self.salt_file.write_bytes(self._salt)
        return hashlib.sha256(self._salt + f"{ip}|{ua}".encode()).hexdigest()[:16]

    def purge(self) -> int:
        if not self.db.exists():
            return 0     # nothing logged yet; don't create a database just to empty it
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retain_days)).isoformat(timespec="seconds")
        with self._connect() as con:
            return con.execute("DELETE FROM visits WHERE at < ?", (cutoff,)).rowcount

    # --- recording --------------------------------------------------------------------

    @staticmethod
    def should_record(method: str, path: str, status: int, content_type: str, headers) -> bool:
        if method != "GET" or path.startswith(_SKIP_PREFIXES) or not content_type.startswith("text/html"):
            return False
        purpose = (headers.get("sec-purpose") or headers.get("purpose") or "").lower()
        return "prefetch" not in purpose and status < 500

    def record(self, *, path: str, query: str, status: int, client_host: str, headers) -> None:
        """Write one page view. Never raises: analytics must not break a page."""
        try:
            via_proxy = client_host in self.trusted
            h = (lambda k: headers.get(k)) if via_proxy else (lambda k: None)
            ip = h("cf-connecting-ip") or (h("x-forwarded-for") or "").split(",")[0].strip() or client_host
            ua = (headers.get("user-agent") or "")[:400]
            info = parse_ua(ua)
            referrer = (headers.get("referer") or "")[:500]
            ref_host = urlparse(referrer).hostname or ""
            if ref_host.lower().removeprefix("www.") == self.site_host.removeprefix("www."):
                ref_host = ""    # internal navigation, not a traffic source
            utm = (parse_qs(query).get("utm_source") or [""])[0][:80]
            row = (datetime.now(timezone.utc).isoformat(timespec="seconds"), path[:300], status,
                   ip, self._visitor_id(ip, ua),
                   h("cf-ipcountry"), h("cf-region"), h("cf-ipcity"), h("cf-timezone"),
                   _float(h("cf-iplatitude")), _float(h("cf-iplongitude")),
                   referrer or None, ref_host or None, utm or None,
                   ua, info["browser"], info["os"], info["device"], int(info["bot"]))
            with self._connect() as con:
                con.execute("INSERT INTO visits (at, path, status, ip, visitor, country, region, city,"
                            " timezone, lat, lon, referrer, ref_host, utm_source, ua, browser, os,"
                            " device, bot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            self._since_purge += 1
            if self._since_purge >= _PURGE_EVERY:
                self._since_purge = 0
                self.purge()
        except (OSError, sqlite3.Error):
            pass

    # --- reporting --------------------------------------------------------------------

    def summary(self, days: int = 30, recent: int = 50) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        if not self.db.exists():
            return {"days": days, "views": 0, "visitors": 0, "bot_views": 0, "recent": []}
        with self._connect() as con:
            def top(expr: str, limit: int = 20, where: str = "", order: str = "views DESC") -> list[dict]:
                sql = (f"SELECT {expr} AS k, COUNT(*) AS views, COUNT(DISTINCT visitor) AS visitors"
                       f" FROM visits WHERE at >= ? AND bot = 0 {where} GROUP BY k"
                       f" ORDER BY {order} LIMIT {int(limit)}")
                return [dict(r) for r in con.execute(sql, (since,))]

            totals = con.execute(
                "SELECT SUM(bot = 0) AS views, COUNT(DISTINCT CASE WHEN bot = 0 THEN visitor END) AS visitors,"
                " SUM(bot) AS bot_views FROM visits WHERE at >= ?", (since,)).fetchone()
            rows = con.execute(
                "SELECT at, path, status, ip, country, region, city, timezone, ref_host, utm_source,"
                " browser, os, device, bot FROM visits WHERE at >= ? ORDER BY id DESC LIMIT ?",
                (since, int(recent))).fetchall()
            points = self._points(con, since)
            countries = top("COALESCE(country, 'unknown')")
            for c in countries:
                c["name"] = (COUNTRIES.get(c["k"]) or [None, None, c["k"]])[2]
            return {
                "days": days,
                "views": totals["views"] or 0,
                "visitors": totals["visitors"] or 0,
                "bot_views": totals["bot_views"] or 0,
                "daily": top("substr(at, 1, 10)", limit=days + 1, order="k"),
                "countries": countries,
                "points": points,
                "cities": top("COALESCE(city, '?') || ', ' || COALESCE(region, '?') || ', ' || COALESCE(country, '?')",
                              where="AND city IS NOT NULL"),
                "pages": top("path"),
                "referrers": top("COALESCE(ref_host, '(direct)')"),
                "campaigns": top("utm_source", where="AND utm_source IS NOT NULL"),
                "browsers": top("browser"), "os": top("os"), "devices": top("device"),
                "recent": [dict(r) for r in rows],
            }

    @staticmethod
    def _points(con: sqlite3.Connection, since: str) -> list[dict]:
        """Map markers: one per city when Cloudflare sent coordinates, else one per country
        at its centroid. Humans only; each carries views + unique visitors."""
        merged: dict[tuple, dict] = {}
        for r in con.execute(
                "SELECT country, region, city, ROUND(lat, 2) AS la, ROUND(lon, 2) AS lo,"
                " COUNT(*) AS views, GROUP_CONCAT(DISTINCT visitor) AS vs"
                " FROM visits WHERE at >= ? AND bot = 0 AND country IS NOT NULL"
                " GROUP BY country, region, city, la, lo", (since,)):
            name = (COUNTRIES.get(r["country"]) or [None, None, r["country"]])[2]
            if r["la"] is not None and r["lo"] is not None:
                key = ("city", r["country"], r["city"], r["la"], r["lo"])
                point = {"lat": r["la"], "lon": r["lo"], "level": "city",
                         "label": ", ".join(x for x in (r["city"], r["region"], name) if x)}
            elif r["country"] in COUNTRIES:
                lat, lon, _ = COUNTRIES[r["country"]]
                key = ("country", r["country"])
                point = {"lat": lat, "lon": lon, "level": "country", "label": name}
            else:
                continue     # "XX" (unknown) or "T1" (Tor) has no place on a map
            m = merged.setdefault(key, {**point, "country": r["country"], "views": 0, "_v": set()})
            m["views"] += r["views"]
            m["_v"].update((r["vs"] or "").split(","))
        out = [{**{k: v for k, v in m.items() if k != "_v"}, "visitors": len(m["_v"] - {""})}
               for m in merged.values()]
        return sorted(out, key=lambda p: p["views"], reverse=True)


# --- terminal view, for use over SSH on the server ---------------------------------------
#   .venv/bin/python -m app.visitors            last 7 days
#   .venv/bin/python -m app.visitors --days 30 --recent 50

def _report(d: dict) -> str:
    def col(rows: list[dict], label=lambda r: r["k"], n: int = 8) -> list[str]:
        return [f"  {str(label(r))[:34]:<34} {r['views']:>6}  {r['visitors']:>6}" for r in rows[:n]] or ["  —"]
    head = f"  {'':<34} {'views':>6}  {'unique':>6}"
    span = "24 hours" if d["days"] == 1 else f"{d['days']} days"
    out = [f"VISITORS · last {span}",
           f"  views {d['views']}   unique visitors {d['visitors']}   bot views {d['bot_views']} (excluded)", ""]
    for title, rows, label in (
            ("COUNTRIES", d.get("countries", []), lambda r: r.get("name") or r["k"]),
            ("PLACES", d.get("points", []), lambda r: r["label"]),
            ("PAGES", d.get("pages", []), lambda r: r["k"]),
            ("REFERRERS", d.get("referrers", []), lambda r: r["k"])):
        out += [title, head, *col(rows, label), ""]
    out.append("RECENT (bots marked *)")
    for r in d.get("recent", []):
        where = ", ".join(x for x in (r["city"], r["country"]) if x) or "unknown"
        who = "*bot" if r["bot"] else f"{r['device']}/{r['browser']}/{r['os']}"
        out.append(f"  {r['at'][:16].replace('T', ' ')}  {where[:22]:<22} {r['path'][:30]:<30} {who[:28]:<28} {r['ip'] or ''}")
    if not d.get("recent"):
        out.append("  no visits in this range")
    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="python -m app.visitors", description="Who visited the site, and from where.")
    ap.add_argument("--days", type=int, default=7, help="look-back window (default 7)")
    ap.add_argument("--recent", type=int, default=25, help="how many recent visits to list (default 25)")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    data_dir = Path(os.environ.get("HUB_DATA_DIR") or root / "data")
    print(_report(Visitors(data_dir).summary(days=max(1, args.days), recent=max(0, args.recent))))
