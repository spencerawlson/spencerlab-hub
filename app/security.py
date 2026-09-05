"""
Automated secret/leak backstop for the publish pipeline.

This is the LAST line, not the only one. The real gate is each source tool refusing to
send confidential material (AuditForge: classification=public/lab; Fieldnote: no open
secret_findings). This scanner catches the obvious things that should never reach a public
page even so. On any hit, publish is refused — the scanner reports WHAT type matched, never
the matched value.
"""
from __future__ import annotations

import re

# (label, pattern). Order does not matter; any hit refuses the publish.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private key block",        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key id",        re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS secret assignment",    re.compile(r"aws_secret_access_key\s*[:=]", re.I)),
    ("Cloudflare API token",     re.compile(r"dns_cloudflare_api_token\s*=\s*[A-Za-z0-9_-]{30,}")),
    ("bearer token",             re.compile(r"\bBearer\s+[A-Za-z0-9._-]{30,}")),
    ("JWT / tunnel token",       re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("GitHub/Slack token",       re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b")),
    ("ZeroTier network id",      re.compile(r"zerotier[^\n]{0,48}\b[0-9a-f]{16}\b", re.I)),
    ("private key file path",    re.compile(r"\b\S+\.(pem|p12|key)\b")),
    ("secret assignment",        re.compile(r"\b(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][^'\"]{12,}['\"]", re.I)),
]


def scan_secrets(*texts: str) -> list[str]:
    """Return the sorted, de-duplicated labels of any secret patterns found across texts."""
    blob = "\n".join(t or "" for t in texts)
    hits = {label for label, pat in _PATTERNS if pat.search(blob)}
    return sorted(hits)
