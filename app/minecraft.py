"""
Live status for the homelab Minecraft server, shown on /projects.

The hub asks the server over the LAN with the standard Server List Ping (the same handshake
the multiplayer screen uses), so nothing new is exposed to the internet and Crafty, the web
panel that manages the server, stays private. Off unless HUB_MINECRAFT_ADDR is set
(host or host:port on the LAN). HUB_MINECRAFT_BEDROCK_PORT (usually 19132) also checks the
Bedrock edition listener (Geyser, for phones and consoles) with a RakNet unconnected ping.

What is published is coarse, like the lab panel: online or not, player count, the server
software's version and the ping time. Never the address, player names or the MOTD.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
from datetime import datetime, timezone

CACHE_FOR = 30          # seconds; every page view and poll shares one probe
TIMEOUT = 3
_PROTOCOL = 767         # any recent protocol number works for a status request


def _varint(n: int) -> bytes:
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _read_varint(sock: socket.socket) -> int:
    n = shift = 0
    for _ in range(5):
        byte = sock.recv(1)
        if not byte:
            raise OSError("connection closed")
        n |= (byte[0] & 0x7F) << shift
        if not byte[0] & 0x80:
            return n
        shift += 7
    raise OSError("bad varint")


def _packet(data: bytes) -> bytes:
    return _varint(len(data)) + data


def ping(host: str, port: int = 25565, timeout: float = TIMEOUT) -> dict:
    """One Server List Ping. Returns the server's status JSON plus round-trip latency."""
    started = time.perf_counter()
    with socket.create_connection((host, port), timeout) as s:
        s.settimeout(timeout)
        h = host.encode()
        s.sendall(_packet(_varint(0) + _varint(_PROTOCOL) + _varint(len(h)) + h
                          + struct.pack(">H", port) + _varint(1)) + _packet(_varint(0)))
        _read_varint(s)                     # packet length
        if _read_varint(s) != 0:            # packet id
            raise OSError("unexpected packet")
        size, data = _read_varint(s), b""
        if size > 1 << 20:
            raise OSError("status too large")
        while len(data) < size:
            chunk = s.recv(size - len(data))
            if not chunk:
                raise OSError("connection closed")
            data += chunk
    status = json.loads(data)
    status["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return status


_RAKNET_MAGIC = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")


def ping_bedrock(host: str, port: int = 19132, timeout: float = TIMEOUT) -> dict:
    """One RakNet unconnected ping, as the Bedrock server list sends. Returns version + latency."""
    started = time.perf_counter()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(b"" + struct.pack(">q", int(time.time() * 1000)) + _RAKNET_MAGIC
                 + struct.pack(">q", 0x5350454E), (host, port))
        data, _ = s.recvfrom(2048)
    if data[:1] != b"" or data[17:33] != _RAKNET_MAGIC:
        raise OSError("unexpected pong")
    size = struct.unpack(">H", data[33:35])[0]
    # MCPE;motd;protocol;version;players;max;server id;...
    fields = data[35:35 + size].decode("utf-8", "replace").split(";")
    return {"version": fields[3] if len(fields) > 3 else "",
            "latency_ms": int((time.perf_counter() - started) * 1000)}


def _parse_addr(addr: str) -> tuple[str, int]:
    host, _, port = addr.strip().partition(":")
    return host, int(port) if port else 25565


class Minecraft:
    def __init__(self, addr: str | None = None, bedrock_port: int | None = None):
        self.addr = addr if addr is not None else os.environ.get("HUB_MINECRAFT_ADDR", "")
        if bedrock_port is None:
            bedrock_port = int(os.environ.get("HUB_MINECRAFT_BEDROCK_PORT") or 0)
        self.bedrock_port = bedrock_port
        self._cached: dict | None = None
        self._at = 0.0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.addr)

    def _bedrock(self, host: str) -> dict | None:
        if not self.bedrock_port:
            return None
        try:
            b = ping_bedrock(host, self.bedrock_port)
        except OSError:
            return {"online": False}
        return {"online": True, "version": b["version"][:20], "latency_ms": b["latency_ms"]}

    def _probe(self) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            host, port = _parse_addr(self.addr)
        except ValueError:
            return {"enabled": True, "online": False, "at": now}
        bedrock = self._bedrock(host)
        extra = {"bedrock": bedrock} if bedrock else {}
        try:
            st = ping(host, port)
        except (OSError, ValueError):
            return {"enabled": True, "online": False, "at": now, **extra}
        players = st.get("players") or {}
        return {"enabled": True, "online": True, "at": now,
                "players": int(players.get("online") or 0), "max_players": int(players.get("max") or 0),
                "version": str((st.get("version") or {}).get("name") or "")[:40],
                "latency_ms": st["latency_ms"], **extra}

    def status(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "online": None}
        with self._lock:
            if self._cached is None or time.time() - self._at >= CACHE_FOR:
                self._cached, self._at = self._probe(), time.time()
            return dict(self._cached)
