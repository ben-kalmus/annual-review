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
from pathlib import Path

BATCH_SIZE = 25  # PRs per GraphQL query; larger batches risk 502s on large repos

# Fields fetched per PR; dismissal events hold the state a dismissed review had before.
PR_FIELDS = """
    number title state isDraft createdAt mergedAt additions deletions changedFiles reviewDecision url
    author { __typename login }
    reviews(first: 100) { totalCount nodes { id state submittedAt author { login } } }
    timelineItems(itemTypes: [REVIEW_DISMISSED_EVENT], first: 100) {
        nodes { ... on ReviewDismissedEvent { previousReviewState review { id } } }
    }
"""


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


def gh(*args: str) -> dict:
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
            return dict()

    return dict()  # unreachable, satisfies type checker


def current_user() -> str:
    """Return the login of the currently authenticated GitHub user."""
    return gh("api", "user")["login"]


def read_cache_since(path: Path) -> str | None:
    """read_cache_since returns the --since date recorded for the cache at path, or None when none was recorded."""
    marker = path.with_suffix(".since")
    return marker.read_text().strip() if marker.exists() else None


def write_cache_since(path: Path, since: str) -> None:
    """write_cache_since records since as the start date of the cache at path."""
    path.with_suffix(".since").write_text(since)


def has_unresolved_dismissals(path: Path) -> bool:
    """has_unresolved_dismissals reports whether the cache at path was written before dismissed reviews kept their earlier state."""
    return any(r["state"] == "DISMISSED" and not r.get("dismissed") for pr in json.loads(path.read_text()) for r in pr["reviews"])


def discover_repos(query: str, since: str, org: str | None = None, date_field: str = "created") -> list[str]:
    """
    Discover all repos containing PRs matching `query` whose `date_field` is on or after `since`.
    If `org` is given, only repos belonging to that GitHub organisation are
    returned. If omitted, all repos (including personal and cross-org) are
    included.

    Uses the search API so no hardcoded repo list is needed.
    Returns a sorted list of 'owner/repo' strings.
    """
    repos: set[str] = set()
    page = 1
    full_query = f"{query}+type:pr+{date_field}:>={since}"
    while True:
        data = gh("api", f"search/issues?q={full_query}&per_page=100&page={page}")
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            break
        for item in items:
            repo = item["repository_url"].removeprefix("https://api.github.com/repos/")
            if org is None or repo.startswith(f"{org}/"):
                repos.add(repo)
        if len(items) < 100:
            break
        page += 1
    return sorted(repos)


def search_pr_numbers(query: str, since: str, date_field: str = "created") -> list[tuple[str, int]]:
    """
    Search GitHub for PRs matching `query` whose `date_field` is on or after `since`.
    Returns a list of (owner/repo, pr_number) tuples.
    Handles pagination automatically.
    """
    results = []
    page = 1
    full_query = f"{query}+type:pr+{date_field}:>={since}"
    while True:
        data = gh("api", f"search/issues?q={full_query}&per_page=100&page={page}")
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            break
        for item in items:
            # repo_url like https://api.github.com/repos/owner/repo-name
            repo = item["repository_url"].removeprefix("https://api.github.com/repos/")
            results.append((repo, item["number"]))
        if len(items) < 100:
            break
        page += 1
    return results


def login(actor: dict | None) -> str | None:
    """login returns the PR author's login, prefixed with app/ for bots as gh prints it."""
    if not actor:
        return None
    return f"app/{actor['login']}" if actor["__typename"] == "Bot" else actor["login"]


def to_review(review: dict, previous_states: dict[str, str]) -> dict:
    """to_review returns the review with a dismissed review's state replaced by its state before dismissal."""
    out = {"author": review["author"]["login"], "state": review["state"], "submittedAt": review["submittedAt"]}
    if review["state"] == "DISMISSED":
        out["state"] = previous_states.get(review["id"], "DISMISSED")
        out["dismissed"] = True
    return out


def to_pr(repo: str, node: dict) -> dict:
    """to_pr returns the GraphQL pull request node in the cached PR shape."""
    reviews = node.pop("reviews")
    if reviews["totalCount"] > len(reviews["nodes"]):
        print(f"\n  Warning: {repo}#{node['number']} has {reviews['totalCount']} reviews, keeping the first {len(reviews['nodes'])}", file=sys.stderr)
    previous_states = {e["review"]["id"]: e["previousReviewState"] for e in node.pop("timelineItems")["nodes"] if e["review"]}
    node["author"] = login(node["author"])
    node["reviews"] = [to_review(r, previous_states) for r in reviews["nodes"] if r["author"]]
    node["repo"] = repo
    return node


def fetch_prs_for_numbers(
    numbers: list[tuple[str, int]],
    label: str = "",
) -> list[dict]:
    """
    Fetch full PR details for a list of (repo, number) pairs, BATCH_SIZE PRs per GraphQL query.
    Prints a progress indicator. Returns sorted list by createdAt.
    """
    unique = list(dict.fromkeys(numbers))
    prs: list[dict] = []
    for start in range(0, len(unique), BATCH_SIZE):
        if label:
            print(f"\r  {label} {min(start + BATCH_SIZE, len(unique))}/{len(unique)}", end="", flush=True)
        batch = unique[start:start + BATCH_SIZE]
        blocks = [
            f'pr{i}: repository(owner: "{repo.split("/")[0]}", name: "{repo.split("/")[1]}") {{ pullRequest(number: {number}) {{ {PR_FIELDS} }} }}'
            for i, (repo, number) in enumerate(batch)
        ]
        found = gh("api", "graphql", "-f", f"query={{ {' '.join(blocks)} }}").get("data") or {}
        prs += [to_pr(repo, found[f"pr{i}"]["pullRequest"]) for i, (repo, _) in enumerate(batch) if found.get(f"pr{i}")]
    if label:
        print()
    return sorted(prs, key=lambda p: p["createdAt"])
