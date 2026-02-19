"""
Shared utilities for GitHub PR fetch scripts.

Used by:
    fetch_prs.py          — PRs authored by a user
    fetch_reviewed_prs.py — PRs reviewed by a user
"""

import json
import subprocess
import sys
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


def gh(*args: str) -> list | dict:
    """Run a gh CLI command and return parsed JSON. Returns [] on error."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: {result.stderr.strip()}", file=sys.stderr)
        return []
    return json.loads(result.stdout)


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
