"""
The activity feed: what changed on the lab, newest first.

Two sources are merged:
- the content itself — every entry's publish date, and any dated "updates" in its meta.json
  (build logs grow this way), so the feed rebuilds from the repo alone;
- a small runtime log on the server (data/activity.jsonl, not in git) for things only the
  running site knows: API publishes, deploys, and agent sweeps changing state.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_MAX_LOG_LINES = 500


class Activity:
    def __init__(self, data_dir: Path, repo_root: Path):
        self.log_file = data_dir / "activity.jsonl"
        self.repo_root = repo_root

    def record(self, kind: str, title: str, url: str | None = None, detail: str | None = None) -> None:
        event = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "kind": kind, "title": title, "url": url, "detail": detail}
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            lines = self.log_file.read_text(encoding="utf-8").splitlines() if self.log_file.exists() else []
            lines = (lines + [json.dumps(event, ensure_ascii=False)])[-_MAX_LOG_LINES:]
            self.log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass    # the feed is a nicety; never fail a request over it

    def _logged(self) -> list[dict]:
        if not self.log_file.exists():
            return []
        out = []
        for line in self.log_file.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def record_deploy(self) -> None:
        """Log a deploy when the running commit differs from the last one logged."""
        try:
            head = subprocess.run(["git", "log", "-1", "--format=%h%x00%s"], cwd=self.repo_root,
                                  capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return
        if "\x00" not in head:
            return
        sha, subject = head.split("\x00", 1)
        last = next((e for e in reversed(self._logged()) if e.get("kind") == "deploy"), None)
        if not last or last.get("detail") != sha:
            self.record("deploy", f"Site updated — {subject}", detail=sha)

    def feed(self, entries: list[dict], limit: int = 12) -> list[dict]:
        events = []
        for e in entries:
            events.append({"at": e.get("date", ""), "kind": "video" if e["type"] == "video" else "post",
                           "title": e["title"], "url": e["url"], "detail": e["category_name"]})
            for u in e.get("updates", []):
                events.append({"at": u.get("date", ""), "kind": "update", "title": e["title"],
                               "url": e["url"], "detail": u.get("note")})
        # API publishes are already covered by the entry itself.
        events += [ev for ev in self._logged() if ev.get("kind") != "publish"]
        events.sort(key=lambda ev: ev.get("at") or "", reverse=True)
        return events[:limit]
