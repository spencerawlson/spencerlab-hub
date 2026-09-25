import asyncio
import json
from pathlib import Path

import pytest

from app import main
from app.lab import Lab
from test_app import _publish, client  # noqa: F401  (client is a fixture)

HA_PATH = Path(__file__).resolve().parents[2] / "SaaS & Portfolio" / "ha-agent-layer"


# --- build logs + activity -----------------------------------------------------------

def test_replace_keeps_site_fields_and_appends_update(client):
    assert _publish(client, status="in-progress", progress=40).status_code == 201
    meta_f = main.CONTENT / "nmap-recon-on-the-lab" / "meta.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    meta["logos"] = ["kalilinux.svg"]
    meta_f.write_text(json.dumps(meta), encoding="utf-8")

    r = _publish(client, replace=True, progress=70, update_note="Scanned the second subnet.")
    assert r.status_code == 201
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    assert meta["logos"] == ["kalilinux.svg"] and meta["status"] == "in-progress"
    assert meta["progress"] == 70 and meta["updates"][0]["note"] == "Scanned the second subnet."

    html = client.get("/pentested/nmap-recon-on-the-lab").text
    assert "Build log" in html and "70%" in html and "Scanned the second subnet." in html
    assert "Scanned the second subnet." in client.get("/").text   # surfaced in the activity feed


@pytest.mark.parametrize("overrides", [{"status": "done-ish"}, {"progress": 140}, {"progress": "half"}])
def test_publish_rejects_bad_build_log_fields(client, overrides):
    assert _publish(client, **overrides).status_code == 422


def test_lab_api_shape_without_agents(client, monkeypatch):
    monkeypatch.setattr(main, "LAB", Lab("https://example.invalid"))
    d = client.get("/api/lab").json()
    assert set(d) >= {"now", "history", "uptime", "agents"}
    assert "offline" in client.get("/").text or d["agents"]["online"]


def test_agents_offline_without_path(monkeypatch):
    monkeypatch.delenv("HA_AGENT_LAYER_PATH", raising=False)
    lab = Lab("https://example.invalid")
    assert not lab.agents_online and "not set" in lab.agents_error


# --- the HA agents, against the real ha-agent-layer checkout when it is present ------

def _sample(**over):
    s = {"at": "2026-09-24T12:00:00+00:00", "cpu": 12.0, "memory": 40.0, "disk": 35.0,
         "latency_ms": 180, "dns": True, "edge_ok": True, "tunnel": True, "site": True}
    return {**s, **over}


@pytest.mark.skipif(not (HA_PATH / "agents").is_dir(), reason="ha-agent-layer not checked out here")
def test_agents_nominal_then_flag_real_problems(monkeypatch):
    monkeypatch.setenv("HA_AGENT_LAYER_PATH", str(HA_PATH))
    lab = Lab("https://example.invalid")
    assert lab.agents_online, lab.agents_error

    lab.samples.extend(_sample() for _ in range(5))
    sweep = asyncio.run(lab.run_sweep())
    assert sweep["errors"] == 0
    assert sweep["attention"] == 0, [r for r in sweep["results"] if r["status"] != "nominal"]

    lab.samples.append(_sample(cpu=97.0, disk=95.0, latency_ms=900, edge_ok=False))
    sweep = asyncio.run(lab.run_sweep())
    by = {r["agent"]: r for r in sweep["results"]}
    assert "high_cpu" in by["observability"]["findings"]
    assert "storage_full" in by["storage"]["findings"]
    assert "high_latency" in by["networking"]["findings"]
    assert "post_remediation_failure" in by["verification"]["findings"]
    assert all(r["status"] != "error" for r in sweep["results"])
