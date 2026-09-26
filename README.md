# spencerlab.tech — the tech hub

A small, self-hosted FastAPI blog and vlog: a working technical journal of what gets
**built, repaired, pentested, assessed, and administered** — as write-ups and self-hosted
videos. Served publicly through the Cloudflare Tunnel on UbuntuServ — no inbound ports,
home IP hidden. AuditForge and Fieldnote publish straight in through `/api/publish`.

## Layout

```
spencerlab-hub/
  app/main.py          routes, feeds, media, the publish API
  app/content.py       loads entries: masthead → post header, TOC, reading time, media URLs
  app/security.py      the secret-scan backstop for publishing
  templates/           base · home · list · post · topics · search · about · 404 · feed.xml
  static/site.css      the design system (liquid glass × cyberpunk: black, neon green, Chakra Petch)
  content/entries/
    <slug>/meta.json   {title, category, date, summary, tags, cover?, video?, poster?, ...}
    <slug>/body.html   the entry body, using the shared component classes
    <slug>/*.png|mp4   media the entry uses, served at /media/<slug>/<file>
  tests/               pytest suite (pip install -r requirements-dev.txt; pytest)
```

Pages: `/` (live lab panel, featured, now building, recent, videos, activity, topics), `/posts`, `/videos`, `/topics`, `/lab`,
`/<category>`, `/<category>/<slug>`, `/tags/<tag>`, `/search?q=`, `/about`, plus
`/feed.xml` (RSS), `/sitemap.xml`, `/robots.txt`, `/healthz`, `/api/lab`, `/api/visitors` (token), `/stats` (private dashboard). Listings paginate at 9.

Categories (fixed, in `app/content.py`): `built`, `repaired`, `pentested`, `assessed`,
`administered`.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
# → http://localhost:8080
```

## Add an entry (by hand)

1. `mkdir content/entries/my-slug`
2. Write `meta.json` (copy an existing one — `category` must be one of the five).
3. Write `body.html` — the article body. Reuse the component classes in
   `static/site.css`: `.term` (command blocks), `.callout .lesson|.gotcha|.fail|.win`,
   `.facts`, `.tablewrap`, `.ladder`, `.pillrow`, `figure`. A leading
   `<header class="masthead">` is optional — the page header is built from `meta.json`,
   and only the masthead's `.byline` is kept.
4. Put images next to it and reference them as `/media/my-slug/<file>`. Optional
   `"cover": "cover.jpg"` sets the card thumbnail (otherwise a topic graphic is drawn).
   `"logos": ["kalilinux.svg"]` puts brand marks (files in `static/logos/`, up to 3) on
   the post's thumbnail and banner — for the tools or products the post is about.
5. Restart (or run with `--reload`). Entries load at startup, newest date first; reading
   time and the "On this page" contents (3+ `<h2>`s) are computed automatically.

### Video posts

Copy the file into the entry folder and name it in `meta.json`:

```json
{ "video": "video.mp4", "poster": "poster.jpg", "duration": "12:04", "captions": "en.vtt" }
```

The post then renders a player and appears under `/videos`. Files are served with HTTP
Range support, so seeking works. Encode for the web before uploading (H.264/AAC MP4 with
`-movflags +faststart`) — every view streams from the homelab through the tunnel.

### Build logs

A post can be a running build log. In `meta.json`:

```json
{ "status": "in-progress", "progress": 40,
  "updates": [{ "date": "2026-09-24", "note": "Second node racked." }] }
```

`status` is `planned`, `in-progress` or `complete`; `progress` (0-100) is optional. Posts
that are planned or in progress appear under **Now building** on the home page, and every
update shows in the activity feed. Through the API, send `status` / `progress` and an
`update_note` with `"replace": true`; the site keeps its own fields (logos, cover, history).

### Embedding a demo (games, WebAssembly)

Put the build under `static/play/<name>/` and add a click-to-launch box to the post body,
so the heavy runtime only loads when a reader asks for it:

```html
<div class="playframe" data-embed-src="/static/play/atm/index.html" data-embed-title="…">
  <img src="/media/<slug>/screenshot.png" alt="…"><button type="button" class="btn primary">▶ Launch</button>
</div>
```

See `play-src/atm/` for how the ATM game was built.

## The live lab panel and HA agents

A background task (`app/lab.py`) samples the host every 30 s: CPU, memory and disk from
`/proc` / `statvfs`, a round-trip to the public `/healthz` through Cloudflare, and
`systemctl is-active` for `cloudflared` and `spencerlab-hub`. It keeps 30 minutes of history
for the sparklines. Every 5 minutes it hands the latest sample to five **ha-agent-layer**
agents (observability, storage, networking, verification, predictive_sentinel). They are
advisory only: their findings are shown on `/lab`, and nothing is executed.

The agent code is **private and not in this repo**. Clone it on the server and point the
service at it; without it the panel shows telemetry and reports the agents as offline.

```bash
git clone git@github.com:spencerawlson/ha-agent-layer.git ~/ha-agent-layer
sudo systemctl edit spencerlab-hub     # add under [Service]:
#   Environment=HA_AGENT_LAYER_PATH=/home/sspady/ha-agent-layer
sudo systemctl restart spencerlab-hub
```

Only coarse numbers are published — no addresses, versions, hostnames or patch levels
(`patch_management` is deliberately not wired in). `/api/lab` serves the same data as JSON.

The activity feed (`app/activity.py`) is built from the content (publish dates, build-log
updates) plus a runtime log at `data/activity.jsonl` (gitignored): deploys (a new git commit
running) and agent sweeps changing state. `HUB_DATA_DIR` moves it; `HUB_LAB_DISABLED=1`
turns the background task off (the tests do this).

## Visitor log

`app/visitors.py` records every HTML page view in `data/visits.db` (SQLite, gitignored):
time, path, status, the visitor's **IP**, a stable visitor id (salted hash of IP + browser,
for unique/returning counts), **country / region / city / timezone**, referrer and
`utm_source`, browser / OS / device, and a bot flag. Static files, media, `/api/*`,
`/healthz`, feeds and prefetches are not recorded.

Location comes from Cloudflare headers, trusted only on requests from localhost (cloudflared
or Nginx), so nobody can spoof an IP or place by hitting the app another way:

- `CF-Connecting-IP` and `CF-IPCountry` arrive by default.
- **City, region and timezone** need one switch: Cloudflare dashboard → the domain → *Rules*
  → *Transform Rules* → *Managed Transforms* → enable **Add visitor location headers**.

Read it with the stats endpoint — off unless `HUB_STATS_TOKEN` is set (use a different
value from the publish token):

```bash
curl -s -H "Authorization: Bearer $HUB_STATS_TOKEN" "https://spencerlab.tech/api/visitors?days=7&recent=100"
```

It returns views, unique visitors and bot views, plus top countries, cities, pages,
referrers, campaigns, browsers, OS, devices, a daily series and the most recent visits
(with IP and location). For ad-hoc questions, query the database on the VM:
`sqlite3 data/visits.db "SELECT at, ip, country, city, path FROM visits ORDER BY id DESC LIMIT 20"`.

**Dashboard: `/stats`.** A private page (noindex, not linked, disallowed in robots.txt,
and never logged itself). It holds no data: it asks for the stats token, keeps it in that
tab's session storage and reads `/api/visitors` with it. It shows views, unique visitors,
countries and bot views for 24 h / 7 / 30 / 90 days; a **visitor map** — the same world
silhouette, equirectangular projection and cyan count bubbles as the Aegis CloudOps Cloud Map
and the DJINN cockpit's geo heatmap (`WORLD_LAND`, copied into
`templates/partials/world_map.html`) — with a location list and each place's recent visits;
views per day; top pages, referrers, countries, browsers, OS and devices; and recent visits.
Bubbles sit on the city when Cloudflare sends coordinates, otherwise on the country's centre
(`app/countries.json`, Google's public country-centroid table).

Raw IPs are personal data: rows older than `HUB_VISITS_RETAIN_DAYS` (default 90) are purged
at startup and periodically. `HUB_VISITS_DISABLED=1` turns logging off.

## Deploy on UbuntuServ (behind the existing tunnel)

The tunnel currently points at `http://localhost:80` (Nginx). Two clean options:

**A — Nginx reverse-proxies to the app (recommended).** Keep the tunnel as-is; run the
hub on `:8080` and let Nginx pass `/` to it:

```nginx
# /etc/nginx/sites-available/spencerlab.tech  (replaces the static root)
server {
    listen 80;
    server_name spencerlab.tech www.spencerlab.tech;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

**B — point the tunnel straight at the app.** In the tunnel's Public Hostname, change the
service to `HTTP → localhost:8080` and stop Nginx. Simpler, one fewer moving part.

Run the app as a service so it survives reboots:

```bash
# /etc/systemd/system/spencerlab-hub.service
[Unit]
After=network.target
[Service]
WorkingDirectory=/home/sspady/spencerlab-hub
ExecStart=/home/sspady/spencerlab-hub/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
Restart=always
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now spencerlab-hub
```

Getting the code onto the VM: `git clone` once the repo exists, or `scp` the folder over
the ZeroTier/host-only address. `python3-venv` and `pip` are all it needs — no build step.

## The publish API (Phase 2 — built)

`POST /api/publish` lets AuditForge and Fieldnote push a finalized entry straight in. It is
**disabled unless `HUB_PUBLISH_TOKEN` is set** — no token, no endpoint (503). Set it in the
systemd unit's environment on the VM, never in the repo.

Guarded three ways:

1. **Bearer token** — `Authorization: Bearer $HUB_PUBLISH_TOKEN` or 401.
2. **Clearance flag** — the caller must send `"cleared_for_publication": true`, which the
   source tool sets *only after its own sensitivity gate passes* (AuditForge
   `classification=public/lab`; Fieldnote no open `secret_findings`). 422 otherwise.
3. **Secret backstop** — `app/security.py` scans the payload for keys, tokens, private-key
   blocks, JWTs, ZeroTier IDs, etc. Any hit refuses the publish (422) and reports the *kind*
   of match, never the value.

Request body:

```json
{
  "title": "Nmap recon on the lab subnet",
  "category": "pentested",           // built | repaired | pentested | assessed | administered
  "summary": "One or two sentences.",
  "body_html": "<div class=\"readwrap\"><section>…</section></div>",
  "source": "fieldnote",             // auditforge | fieldnote | hand
  "cleared_for_publication": true,
  "tags": ["nmap", "lab"],
  "slug": "optional-explicit-slug",  // else derived from the title
  "date": "2026-09-05"               // else today
}
```

On success: `201 {"status":"published","url":"/pentested/…","slug":"…"}`. The entry is
written to `content/entries/<slug>/` and picked up immediately.

- An existing slug returns **409** unless the request sends `"replace": true`.
- Inline `data:` images in `body_html` are written out as files (identical images once)
  and the body is rewritten to `/media/<slug>/…`, so pages stay light.
- Videos are not sent through the API — copy them into the entry folder (see above).

Body HTML should use the shared component classes (`.term`, `.callout`, `.facts`, …) so
published entries match the house style. The next sub-phase adds the actual **Publish**
buttons in AuditForge (Tauri/Rust) and Fieldnote (Node) that render a finalized doc to that
HTML and POST it here.
