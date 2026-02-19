"""
Shared utilities for GitHub PR fetch scripts.

Used by:
    fetch_prs.py          — PRs authored by a user
    fetch_reviewed_prs.py — PRs reviewed by a user
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone

START_DATE = "2025-05-28"
BATCH_SIZE = 50  # safe page size that avoids GraphQL 502s on large repos

# Fields to fetch per PR via gh pr view
PR_FIELDS = ",".join([
    "number",
    "title",
    "state",
    "isDraft",
    "createdAt",
    "mergedAt",
    "closedAt",
    "additions",
    "deletions",
    "changedFiles",
    "baseRefName",
    "headRefName",
    "reviewDecision",
    "reviews",
    "labels",
    "body",
    "url",
    "author",
])


_RATE_LIMIT_PHRASES = ("rate limit", "secondary rate", "429")
_MAX_RETRIES = 5
_SECONDARY_RATE_WAIT = 60  # seconds to wait on secondary rate limit hits


def _wait_for_rate_limit_reset() -> None:
    """Query the API rate limit and sleep until the reset window opens."""
    try:
        result = subprocess.run(
            ["gh", "api", "rate_limit", "--jq", ".rate.reset"],
            capture_output=True, text=True,
        )
        reset_ts = int(result.stdout.strip())
        wait = max(0, reset_ts - int(time.time())) + 2  # +2s buffer
        print(f"\n  Rate limit hit — waiting {wait}s for reset...", file=sys.stderr)
        time.sleep(wait)
    except Exception:
        # If we can't determine the reset time, fall back to a fixed wait
        print(f"\n  Rate limit hit — waiting {_SECONDARY_RATE_WAIT}s...", file=sys.stderr)
        time.sleep(_SECONDARY_RATE_WAIT)


def gh(*args: str) -> list | dict:
    """
    Run a gh CLI command and return parsed JSON.
    Retries automatically on rate limit errors with appropriate back-off.
    Raises RuntimeError if all retries are exhausted.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        result = subprocess.run(["gh", *args], capture_output=True, text=True)

        if result.returncode == 0:
            return json.loads(result.stdout)

        stderr = result.stderr.strip()

        if any(phrase in stderr.lower() for phrase in _RATE_LIMIT_PHRASES):
            if attempt == _MAX_RETRIES:
                raise RuntimeError(f"Rate limit persists after {_MAX_RETRIES} retries. Aborting.")
            _wait_for_rate_limit_reset()
        else:
            # Non-rate-limit error — warn and return empty (existing behaviour)
            print(f"  Warning: {stderr}", file=sys.stderr)
            return []

    return []  # unreachable, satisfies type checker


def current_user() -> str:
    """Return the login of the currently authenticated GitHub user."""
    return gh("api", "user")["login"]


def discover_repos(query: str, since: str, org: str = "algolia") -> list[str]:
    """
    Discover all repos containing PRs matching `query` since `since`,
    filtered to the given GitHub organisation.

    Uses the search API so no hardcoded repo list is needed.
    Returns a sorted list of 'org/repo' strings.
    """
    repos: set[str] = set()
    page = 1
    full_query = f"{query}+type:pr+created:>={since}"
    while True:
        data = gh("api", f"search/issues?q={full_query}&per_page=100&page={page}")
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            break
        for item in items:
            repo = item["repository_url"].removeprefix("https://api.github.com/repos/")
            if repo.startswith(f"{org}/"):
                repos.add(repo)
        if len(items) < 100:
            break
        page += 1
    return sorted(repos)


def search_pr_numbers(query: str, since: str) -> list[tuple[str, int]]:
    """
    Search GitHub for PRs matching `query` created on or after `since`.
    Returns a list of (owner/repo, pr_number) tuples.
    Handles pagination automatically.
    """
    results = []
    page = 1
    full_query = f"{query}+type:pr+created:>={since}"
    while True:
        data = gh("api", f"search/issues?q={full_query}&per_page=100&page={page}")
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            break
        for item in items:
            # repo_url like https://api.github.com/repos/algolia/metis
            repo = item["repository_url"].removeprefix("https://api.github.com/repos/")
            results.append((repo, item["number"]))
        if len(items) < 100:
            break
        page += 1
    return results


def fetch_pr(repo: str, number: int) -> dict | None:
    """
    Fetch full details for a single PR and return a normalised dict.
    Returns None if the fetch fails.
    """
    pr = gh("pr", "view", str(number), "--repo", repo, "--json", PR_FIELDS)
    if not pr or not isinstance(pr, dict):
        return None

    pr["repo"] = repo
    pr["labels"] = [lb["name"] for lb in pr.get("labels", [])]
    pr["reviews"] = [
        {
            "author": r["author"]["login"],
            "state": r["state"],
            "submittedAt": r.get("submittedAt", ""),
        }
        for r in pr.get("reviews", [])
        if r.get("author")
    ]
    # Flatten author to just the login string
    if isinstance(pr.get("author"), dict):
        pr["author"] = pr["author"].get("login", "")

    return pr


def fetch_prs_for_numbers(
    numbers: list[tuple[str, int]],
    label: str = "",
) -> list[dict]:
    """
    Fetch full PR details for a list of (repo, number) pairs.
    Prints a progress indicator. Returns sorted list by createdAt.
    """
    results: dict[tuple[str, int], dict] = {}
    total = len(numbers)
    for i, (repo, number) in enumerate(numbers, 1):
        if label:
            print(f"\r  {label} {i}/{total}", end="", flush=True)
        pr = fetch_pr(repo, number)
        if pr:
            results[(repo, number)] = pr
    if label:
        print()  # newline after progress
    return sorted(results.values(), key=lambda p: p["createdAt"])
