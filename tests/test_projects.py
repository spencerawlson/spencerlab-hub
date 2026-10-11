import json
import socket
import struct
import threading

from app import main
from app.minecraft import _RAKNET_MAGIC, Minecraft, _varint
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


def _fake_bedrock() -> tuple[int, threading.Thread]:
    """A one-shot UDP listener that answers an unconnected ping like Geyser does."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))

    def serve():
        with srv:
            data, peer = srv.recvfrom(2048)
            motd = b'MCPE;secret motd;2193;26.52;3;20;123;Another Geyser server.;Survival;1;19132;19132;'
            srv.sendto(b"" + data[1:9] + struct.pack(">q", 42) + _RAKNET_MAGIC
                       + struct.pack(">H", len(motd)) + motd, peer)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return srv.getsockname()[1], t


def test_minecraft_bedrock_listener():
    port, t = _fake_server()
    bport, bt = _fake_bedrock()
    st = Minecraft(f"127.0.0.1:{port}", bedrock_port=bport).status()
    t.join(2), bt.join(2)
    assert st["bedrock"]["online"] is True and st["bedrock"]["version"] == "26.52"
    assert "motd" not in json.dumps(st)
    assert "bedrock" not in Minecraft(f"127.0.0.1:{port}", bedrock_port=0).status()


def test_minecraft_offline_and_disabled():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()                                   # nothing listening there now
    st = Minecraft(f"127.0.0.1:{port}", bedrock_port=port).status()
    assert st["online"] is False and st["bedrock"] == {"online": False}
    assert Minecraft("").status() == {"enabled": False, "online": None}


def test_projects_page_and_api(client, monkeypatch):
    port, t = _fake_server()
    bport, bt = _fake_bedrock()
    monkeypatch.setattr(main, "MINECRAFT", Minecraft(f"127.0.0.1:{port}", bedrock_port=bport))
    html = client.get("/projects").text
    t.join(2), bt.join(2)
    assert "Bedrock" in html and "26.52" in html
    assert "Road to CISSP" in html and "https://road2cissp.com" in html
    assert "3/20 players" in html and 'aria-current="page">Projects' in html
    assert client.get("/api/minecraft").json()["online"] is True   # served from the cache
    assert "/projects" in client.get("/sitemap.xml").text


def test_projects_link_to_real_entries():
    entries = {e["slug"]: e for e in main.load_entries(main.ROOT / "content" / "entries")}
    for p in main.PROJECTS:
        assert p["post"] in entries, p["post"]
