"""
Shared formatting utilities used across analyse_*.py scripts.
"""

import sys
from pathlib import Path


def warn_if_stale_cache(path: Path, cached_since: str | None, since: str) -> None:
    """warn_if_stale_cache prints a warning when the cache at path starts after since or has no recorded start."""
    if cached_since and cached_since <= since:
        return
    print(
        f"Warning: {path} holds data since {cached_since or 'an unknown date'}, "
        f"but --since is {since}. Pass --force to re-fetch.",
        file=sys.stderr,
    )


def fmt_duration(days: float) -> str:
    """Format a duration: use minutes when under a day, days otherwise."""
    if days < 1:
        return f"{days * 24 * 60:.0f} min"
    return f"{days:.1f} days"


def fmt_int(n: int | float) -> str:
    return f"{n:,.0f}"


def pct(n: int | float, total: int | float) -> str:
    return f"{n / total * 100:.0f}%" if total else "0%"


def bar(ratio: float, width: int = 20) -> str:
    """Block bar scaled to `width` chars representing 100%."""
    filled = round(min(ratio, 1.0) * width)
    return "█" * filled + "░" * (width - filled)
