"""Raport z nieudanego builda i gotowe zgloszenie na GitHubie.

Kazdy nierozpoznany blad trafiajacy do nas jako zgloszenie z pelnym
kontekstem staje sie kandydatem na nowy wzorzec w patterns.py.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from urllib.parse import urlencode

from exelent.constants import APP_NAME

# Placeholder until the project is published under its real GitHub org/name.
REPO_URL = "https://github.com/exelent-app/exelent"

# Common practical ceiling for URL length across browsers, proxies and
# GitHub itself (well documented to choke somewhere around 8 KB). Kept with
# headroom below that so we never rely on being exactly at the edge.
MAX_URL_CHARS = 7500

_TITLE = "Build nie powiodl sie"
_TRUNCATED_SUFFIX = "\n...(log skrocony)...\n"


def tail(log: str, lines: int = 40) -> str:
    return "\n".join(log.splitlines()[-lines:])


def _context(plan_summary: str) -> str:
    return (
        f"**{APP_NAME}**\n\n"
        f"- Projekt: {plan_summary}\n"
        f"- System: {platform.platform()}\n"
        f"- Python EXElent: {sys.version.split()[0]}\n"
    )


def _build_url(body: str) -> str:
    query = urlencode({"title": _TITLE, "body": body})
    return f"{REPO_URL}/issues/new?{query}"


def github_issue_url(log: str, plan_summary: str) -> str:
    """Build a pre-filled "new issue" URL with log tail and project context.

    ``urlencode`` percent-escapes most non-alphanumeric bytes, so a raw
    character budget on the log excerpt does not bound the final URL length:
    a log heavy in punctuation or non-ASCII text can expand several times
    over on encoding. Instead we measure the *actual* encoded URL and keep
    halving the excerpt until it genuinely fits, which holds even for
    multi-megabyte logs full of special characters.
    """
    header = _context(plan_summary)
    excerpt = tail(log, 60)
    body = f"{header}\n\n```\n{excerpt}\n```\n"
    url = _build_url(body)

    while len(url) > MAX_URL_CHARS and excerpt:
        excerpt = excerpt[: len(excerpt) // 2]
        suffix = _TRUNCATED_SUFFIX if excerpt else "(log skrocony)\n"
        body = f"{header}\n\n```\n{excerpt}{suffix}```\n"
        url = _build_url(body)

    return url


def write_report(log: str, dest: Path, plan_summary: str) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"{_context(plan_summary)}\n\n{log}\n", encoding="utf-8")
    return dest
