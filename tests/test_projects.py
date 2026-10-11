import json
import socket
import threading

from app import main
from app.minecraft import Minecraft, _varint
from test_app import client  # noqa: F401  (client is a fixture)

STATUS = {"version": {"name": "Paper 26.2", "protocol": 776}, "players": {"max": 20, "online": 3,
          "sample": [{"name": "someone", "id": "x"}]}, "description": "secret motd"}


def _fake_server() -> tuple[int, threading.Thread]:
    """A one-shot TCP server that answers a status request like a Minecraft server."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        with conn, srv:
            conn.recv(4096)
            body = json.dumps(STATUS).encode()
            payload = _varint(0) + _varint(len(body)) + body
            conn.sendall(_varint(len(payload)) + payload)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return srv.getsockname()[1], t


def test_minecraft_status_is_coarse():
    port, t = _fake_server()
    st = Minecraft(f"127.0.0.1:{port}").status()
    t.join(2)
    assert st["online"] is True and st["players"] == 3 and st["max_players"] == 20
    assert st["version"] == "Paper 26.2" and isinstance(st["latency_ms"], int)
    # Player names, the MOTD and the address never leave the probe.
    assert "someone" not in json.dumps(st) and "motd" not in json.dumps(st)
    assert "127.0.0.1" not in json.dumps(st)


def test_minecraft_offline_and_disabled():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()                                   # nothing listening there now
    assert Minecraft(f"127.0.0.1:{port}").status()["online"] is False
    assert Minecraft("").status() == {"enabled": False, "online": None}


def test_projects_page_and_api(client, monkeypatch):
    port, t = _fake_server()
    monkeypatch.setattr(main, "MINECRAFT", Minecraft(f"127.0.0.1:{port}"))
    html = client.get("/projects").text
    t.join(2)
    assert "Road to CISSP" in html and "https://road2cissp.com" in html
    assert "3/20 players" in html and 'aria-current="page">Projects' in html
    assert client.get("/api/minecraft").json()["online"] is True   # served from the cache
    assert "/projects" in client.get("/sitemap.xml").text


def test_projects_link_to_real_entries():
    entries = {e["slug"]: e for e in main.load_entries(main.ROOT / "content" / "entries")}
    for p in main.PROJECTS:
        assert p["post"] in entries, p["post"]
