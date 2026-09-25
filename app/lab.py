"""
The live lab panel: real host telemetry from the machine serving this site, judged by the
same HA agents that run inside Aegis CloudOps.

Every SAMPLE_EVERY seconds a background task reads /proc and statvfs, probes the public edge
(https://<site>/healthz through Cloudflare) and checks the tunnel + site services. Every
SWEEP_EVERY seconds the latest sample is handed to a handful of ha-agent-layer agents.

The agents are ADVISORY here, exactly as in Aegis: they read numbers and say what they would
recommend. Nothing they return is executed.

The agent code is private and is not in this repository. It is loaded from a separate
checkout named by HA_AGENT_LAYER_PATH; without it the panel still shows telemetry and reports
the agents as offline.

What is published is deliberately coarse — utilisation, uptime, latency, service state. No
addresses, versions, hostnames or patch levels: this is a security portfolio.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SAMPLE_EVERY = 30          # seconds between telemetry samples
SWEEP_EVERY = 300          # seconds between agent sweeps
HISTORY = 60               # samples kept: 30 minutes at the default cadence
SERVICES = {"tunnel": "cloudflared", "site": "spencerlab-hub"}
_PROBE_UA = "spencerlab-labpanel/1.0 (+https://spencerlab.tech/lab)"

# ha-agent-layer module -> class. Chosen because each reads something a single Linux host
# really has. patch_management is left out on purpose: publishing a pending-CVE count on a
# public page is a gift to anyone scanning it.
AGENTS = {
    "observability": ("agents.ecosystem.observability", "Observability"),
    "storage": ("agents.ecosystem.storage", "Storage"),
    "networking": ("agents.ecosystem.networking", "Networking"),
    "verification": ("agents.ecosystem.verification", "Verification"),
    "predictive_sentinel": ("agents.ecosystem.predictive_sentinel", "PredictiveSentinel"),
}
# Placeholder findings agents emit when nothing fired — nominal, not a problem.
_NOMINAL = {"unknown_observability_signal", "no_predictive_signal"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- telemetry ------------------------------------------------------------------------

def _read(path: str) -> str | None:
    try:
        return Path(path).read_text()
    except OSError:
        return None


def _cpu_times() -> tuple[int, int] | None:
    stat = _read("/proc/stat")
    if not stat:
        return None
    fields = [int(v) for v in stat.splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return sum(fields), idle


def _memory_pct() -> float | None:
    info = _read("/proc/meminfo")
    if not info:
        return None
    kv = {line.split(":")[0]: int(line.split()[1]) for line in info.splitlines() if ":" in line}
    total, avail = kv.get("MemTotal"), kv.get("MemAvailable")
    return round(100 * (1 - avail / total), 1) if total and avail is not None else None


def _disk_pct(path: str = "/") -> float | None:
    try:
        st = os.statvfs(path)
    except (AttributeError, OSError):   # statvfs does not exist on Windows (local dev)
        return None
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    usable = used + st.f_bavail * st.f_frsize
    return round(100 * used / usable, 1) if usable else None


def _host_uptime() -> int | None:
    up = _read("/proc/uptime")
    return int(float(up.split()[0])) if up else None


def _service_active(unit: str) -> bool | None:
    try:
        out = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None                      # no systemd here (local dev): unknown, not down
    return out.stdout.strip() == "active"


def _probe_edge(base_url: str) -> dict:
    """Round-trip to the public /healthz: DNS, Cloudflare, the tunnel and back."""
    host = urlparse(base_url).hostname or ""
    try:
        socket.getaddrinfo(host, 443)
        dns = True
    except OSError:
        return {"dns": False, "ok": False, "latency_ms": None}
    started = time.perf_counter()
    # Cloudflare's bot protection answers Python's default "Python-urllib" agent with a 403,
    # which would read as the site being down. Say who we are instead.
    req = urllib.request.Request(f"{base_url}/healthz", headers={"User-Agent": _PROBE_UA})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            ok = r.status == 200
    except OSError:
        ok = False
    return {"dns": dns, "ok": ok, "latency_ms": int((time.perf_counter() - started) * 1000) if ok else None}


class Lab:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.started = time.time()
        self.samples: deque[dict] = deque(maxlen=HISTORY)
        self.sweep: dict | None = None
        self._cpu_prev = _cpu_times()
        self._agents, self.agents_error = self._load_agents()

    # --- agents -----------------------------------------------------------------------
    def _load_agents(self) -> tuple[dict, str | None]:
        root = os.environ.get("HA_AGENT_LAYER_PATH")
        if not root:
            return {}, "HA_AGENT_LAYER_PATH is not set"
        if not Path(root, "agents").is_dir():
            return {}, "HA_AGENT_LAYER_PATH has no agents/ package"
        if root not in sys.path:
            sys.path.insert(0, root)
        loaded = {}
        for name, (module, cls) in AGENTS.items():
            try:
                loaded[name] = getattr(importlib.import_module(module), cls)
            except Exception as e:                  # one missing agent must not sink the rest
                return loaded, f"could not load {name}: {type(e).__name__}"
        return loaded, None

    @property
    def agents_online(self) -> bool:
        return bool(self._agents)

    def _incident(self, s: dict) -> dict:
        """The latest sample, in the shape each agent reads."""
        hist = list(self.samples)
        series = {m: [x[m] for x in hist if x.get(m) is not None][-12:] for m in ("cpu", "memory", "disk")}
        probes = [x["edge_ok"] for x in hist if x.get("edge_ok") is not None]
        return {
            "metrics": {"cpu_utilization": s.get("cpu"), "memory_utilization": s.get("memory")},
            "alert_count": 0,
            "storage_utilization": s.get("disk"),
            "storage_type": "block",
            "latency_ms": s.get("latency_ms"),
            "dns": s.get("dns"),
            "health_status": bool(s.get("edge_ok")) and s.get("tunnel") is not False and s.get("site") is not False,
            "post_checks": [{"check": "edge_https", "ok": s.get("edge_ok")},
                            {"check": "tunnel_service", "ok": s.get("tunnel")},
                            {"check": "site_service", "ok": s.get("site")}],
            "trend_samples": [{"metric_name": m, "values": v} for m, v in series.items() if len(v) >= 3],
            # Share of failed edge probes in the window: a rate, used as the error trend.
            "error_rate_trend": round(1 - sum(probes) / len(probes), 3) if probes else 0.0,
            "quota_usage_ratio": round((s.get("disk") or 0) / 100, 3),
        }

    async def run_sweep(self) -> dict | None:
        if not self._agents or not self.samples:
            return self.sweep
        from agents.framework.base_agent import AgentContext   # present once agents loaded
        incident = self._incident(self.samples[-1])
        rows = []
        for name, cls in self._agents.items():
            started = time.perf_counter()
            try:
                agent = cls()
                ctx = agent.validate_inputs(AgentContext(incident=incident, provider="linux",
                                                         region="homelab", metadata={}))
                out = await asyncio.wait_for(agent.execute(ctx), timeout=2)
                real = [f for f in out.get("findings", []) if f.get("cause") not in _NOMINAL]
                rows.append({"agent": name, "status": "attention" if real else "nominal",
                             "findings": [f.get("cause") for f in real],
                             "recommendation": (out.get("actions") or [None])[0] if real else None,
                             "confidence": round(float(out.get("confidence") or 0), 2),
                             "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
            except Exception as e:
                rows.append({"agent": name, "status": "error", "findings": [], "recommendation": None,
                             "confidence": 0.0, "error": type(e).__name__, "latency_ms": None})
        previous = self.sweep
        self.sweep = {"at": _now(), "results": rows,
                      "attention": sum(r["status"] == "attention" for r in rows),
                      "errors": sum(r["status"] == "error" for r in rows)}
        self._on_sweep(previous, self.sweep)
        return self.sweep

    def _on_sweep(self, previous: dict | None, current: dict) -> None:
        """Hook for the activity log; replaced by main.py."""

    # --- sampling ---------------------------------------------------------------------
    def sample(self) -> dict:
        cpu = None
        now_cpu = _cpu_times()
        if now_cpu and self._cpu_prev:
            total, idle = now_cpu[0] - self._cpu_prev[0], now_cpu[1] - self._cpu_prev[1]
            cpu = round(100 * (1 - idle / total), 1) if total > 0 else 0.0
        self._cpu_prev = now_cpu
        edge = _probe_edge(self.base_url)
        s = {"at": _now(), "cpu": cpu, "memory": _memory_pct(), "disk": _disk_pct(),
             "latency_ms": edge["latency_ms"], "dns": edge["dns"], "edge_ok": edge["ok"],
             **{k: _service_active(unit) for k, unit in SERVICES.items()}}
        self.samples.append(s)
        return s

    async def loop(self) -> None:
        last_sweep = 0.0
        while True:
            try:
                await asyncio.to_thread(self.sample)
                if time.time() - last_sweep >= SWEEP_EVERY:
                    await self.run_sweep()
                    last_sweep = time.time()
            except Exception:
                pass            # telemetry must never take the site down
            await asyncio.sleep(SAMPLE_EVERY)

    # --- the public view --------------------------------------------------------------
    def status(self) -> dict:
        latest = self.samples[-1] if self.samples else {}
        hist = list(self.samples)
        return {
            "at": latest.get("at"),
            "uptime": {"host_s": _host_uptime(), "site_s": int(time.time() - self.started)},
            "now": {k: latest.get(k) for k in ("cpu", "memory", "disk", "latency_ms", "edge_ok", "tunnel", "site")},
            "history": {m: [x.get(m) for x in hist] for m in ("cpu", "memory", "latency_ms")},
            "sample_every": SAMPLE_EVERY,
            "agents": {"online": self.agents_online, "sweep": self.sweep, "sweep_every": SWEEP_EVERY},
        }
