"""
The /projects showcase: the things running in and around the lab, each linking to its
write-up on this site and, where it has one, its own public home.

`post` is an entry slug; the card links to it when that entry exists. `live` names a
live-status widget the page renders on the card (only "minecraft" today).
"""
from __future__ import annotations

PROJECTS = [
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
              "two-node cluster. It is where the Minecraft server lives.",
     "tags": ["Proxmox VE", "KVM", "Debian"],
     "post": "proxmox-third-host", "status": "in-progress"},
    {"slug": "minecraft", "name": "Minecraft server", "kind": "Self-hosted",
     "logo": "linux.svg",
     "blurb": "A Paper server on its own VM, managed through Crafty Controller. The panel is "
              "LAN-only; this card shows the server's live status.",
     "tags": ["Paper", "Crafty Controller", "Java"],
     "post": "minecraft-server-crafty", "live": "minecraft"},
]
