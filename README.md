# spencerlab.tech — the tech hub

A small, self-hosted FastAPI site: a working technical journal of what gets **built,
repaired, pentested, assessed, and administered**. Replaces srspady.com. Served publicly
through the Cloudflare Tunnel already running on UbuntuServ — no inbound ports, home IP
hidden.

This is **Hub v0**: the read side. Entries are flat files on disk. Phase 2 adds the
authenticated publish API so AuditForge and Fieldnote can push finalized, sanitized docs
straight in.

## Layout

```
spencerlab-hub/
  app/main.py          FastAPI: home, /{category}, /{category}/{slug}, /healthz
  templates/           base · home · category · entry  (Jinja2)
  static/hub.css       the whole design system (IBM Plex · indigo · status accents)
  content/entries/
    <slug>/meta.json   {title, category, date, summary, tags, ...}
    <slug>/body.html   the entry body, using the shared component classes
```

Categories (fixed, in `app/main.py`): `built`, `repaired`, `pentested`, `assessed`,
`administered`.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
# → http://localhost:8080
```

## Add an entry (by hand, for now)

1. `mkdir content/entries/my-slug`
2. Write `meta.json` (copy an existing one — `category` must be one of the five).
3. Write `body.html` — the article body. Reuse the component classes already in
   `static/hub.css`: `.term` (command blocks), `.callout .lesson|.gotcha|.fail|.win`,
   `.facts`, `.tablewrap`, `.ladder`, `.pillrow`, `figure`.
4. Restart (or run with `--reload`). Entries are loaded at startup, newest date first.

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

Body HTML should use the shared component classes (`.term`, `.callout`, `.facts`, …) so
published entries match the house style. The next sub-phase adds the actual **Publish**
buttons in AuditForge (Tauri/Rust) and Fieldnote (Node) that render a finalized doc to that
HTML and POST it here.
