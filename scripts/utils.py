"""
Shared utilities used across the fetch and analyse scripts.
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# START_DATE is the default --since for every script.
START_DATE = "2025-05-28"


def load_dotenv(dotenv_path: Path = REPO_ROOT / ".env") -> None:
    """load_dotenv copies KEY=VALUE pairs from dotenv_path into os.environ without overriding the shell."""
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def add_email_arg(parser: argparse.ArgumentParser) -> None:
    """add_email_arg adds --email for the Atlassian user, defaulting to JIRA_EMAIL, so call load_dotenv first."""
    default = os.environ.get("JIRA_EMAIL")
    parser.add_argument(
        "--email",
        default=default,
        required=default is None,
        help="Atlassian email of the person to fetch or analyse (default: JIRA_EMAIL)",
    )


def name_from_email(email: str) -> str:
    """name_from_email returns the part of email before the @, used to name Atlassian data files."""
    return email.partition("@")[0]


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
