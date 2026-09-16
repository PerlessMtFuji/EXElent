"""Recently used paths. A plain JSON file stores folder history rather than
build configuration, so users do not have to find the same folders again.

Every operation fails safely in both directions: a corrupt or unavailable file
returns an empty list, and a failed write does not interrupt folder selection.
The list is a convenience and must never prevent the application from starting.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from exelent.runtime.paths import state_dir

LIMIT = 5


def _file() -> Path:
    return state_dir() / "recent.json"


def load_recent(limit: int = LIMIT) -> list[Path]:
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    result: list[Path] = []
    for item in raw:
        path = Path(str(item))
        if path.exists() and path not in result:
            result.append(path)
    return result[:limit]


def display_labels(paths: Sequence[Path]) -> list[str]:
    """Napisy na kafelki — najkrotsze, jakie jeszcze rozrozniaja wpisy.

    `path.name` alone is insufficient: `Downloads\\test\\test.txt` and
    `Downloads\\test.txt` are both named "test.txt", so the user saw two
    identical tiles leading to different places with no way to distinguish them.

    ONLY colliding entries grow; the rest stay short because displaying the
    full path on every tile would be worse than the collision being fixed.
    """
    parts = [path.parts for path in paths]
    depths = [1] * len(paths)
    # Each pass adds one directory level to entries still indistinguishable.
    # Bounding the loop by the longest path guarantees termination even when
    # two entries cannot be distinguished at all (relative and absolute paths
    # with the same suffix).
    for _ in range(max((len(p) for p in parts), default=1)):
        labels = [_tail(parts[i], depths[i]) for i in range(len(paths))]
        counts = Counter(labels)
        grew = False
        for i, label in enumerate(labels):
            if counts[label] > 1 and depths[i] < len(parts[i]):
                depths[i] += 1
                grew = True
        if not grew:
            break
    return [_tail(parts[i], depths[i]) for i in range(len(paths))]


def _tail(parts: tuple[str, ...], depth: int) -> str:
    return str(Path(*parts[-depth:])) if parts else ""


def remember(path: Path) -> None:
    path = Path(path).resolve()
    entries = [path, *(p for p in load_recent(limit=LIMIT * 2) if p != path)]
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        _file().write_text(
            json.dumps([str(p) for p in entries[:LIMIT]], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
