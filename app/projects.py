"""
The /projects showcase: the things running in and around the lab, each linking to its
write-up on this site and, where it has one, its own public home.

`post` is an entry slug; the card links to it when that entry exists. `live` names a
live-status widget the page renders on the card (only "minecraft" today).
"""
from __future__ import annotations

PROJECTS = [
    {"slug": "aegis-cloudops", "name": "Aegis CloudOps", "kind": "Cloud · SaaS",
     "logo": "aegis.png",
     "blurb": "AI-assisted cloud operations: live health, cost anomalies and security findings, "
              "with consented fixes. New: a Cloud Migration Readiness assessment. Production now "
              "runs in this homelab behind a Cloudflare Tunnel.",
     "tags": ["Python", "FastAPI", "React", "PostgreSQL", "Docker", "Caddy"],
     "link": "https://aegiscloudops.io", "link_text": "aegiscloudops.io",
     "post": "the-great-migration"},
    {"slug": "fishing-rod-terminal", "name": "Fishing Rod Terminal", "kind": "SaaS · Data",
     "logo": "fishingrod.png",
     "blurb": "A market-intelligence terminal: live signals, per-asset bias, macro-cycle scoring "
              "and scenario analytics. It shares the Aegis backend, so it moved into the lab too.",
     "tags": ["Python", "FastAPI", "WebSockets", "PostgreSQL"],
     "link": "https://fishingrodterminal.io", "link_text": "fishingrodterminal.io",
     "post": "aegis-market-readiness-review"},
    {"slug": "domainfolio", "name": "Domainfolio", "kind": "Side project",
     "logo": "typescript.svg",
     "blurb": "One self-hosted app that serves a for-sale page for every domain I own, routed on "
              "the Host header, with an offers inbox and per-domain visit stats.",
     "tags": ["Next.js", "TypeScript", "SQLite", "Docker", "Cloudflare Tunnel"],
     "link": "https://domainfolio.site", "link_text": "domainfolio.site",
     "post": "domainfolio", "status": "in-progress"},
    {"slug": "road-to-cissp", "name": "Road to CISSP", "kind": "Learning platform",
     "logo": "react.svg",
     "blurb": "A study platform from IT fundamentals up to CISSP: guided tracks, career paths, "
              "an AI tutor and hands-on labs, with progress synced to your account.",
     "tags": ["React", "Vite", "FastAPI", "PostgreSQL", "OAuth"],
     "link": "https://road2cissp.com", "link_text": "road2cissp.com",
     "post": "road-to-cissp", "status": "in-progress"},
    {"slug": "proxmox-third-node", "name": "A third Proxmox host", "kind": "Homelab",
     "logo": "proxmox.svg",
     "blurb": "A third machine running Proxmox VE as a standalone host, separate from the "
              "two-node cluster. It runs the Minecraft server and, since the Great Migration, "
              "production for Aegis and Fishing Rod, backed up nightly to the Time Capsule.",
     "tags": ["Proxmox VE", "KVM", "vzdump"],
     "post": "proxmox-third-host", "status": "in-progress"},
    {"slug": "minecraft", "name": "Minecraft server", "kind": "Self-hosted",
     "logo": "linux.svg",
     "blurb": "A Paper server on its own VM, managed through Crafty Controller. Geyser lets "
              "phones and consoles (Bedrock) join the same world as Java players.",
     "tags": ["Paper", "Geyser", "Crafty Controller"],
     "post": "minecraft-server-crafty", "live": "minecraft"},
]
