#!/usr/bin/env python3
"""
Fetch all PRs reviewed by a GitHub user. Repos are discovered dynamically
via the GitHub search API — no hardcoded list required. Own PRs are excluded.

The `your_reviews` field on each PR contains only the reviews left by the
specified author, making it easy to see APPROVED / CHANGES_REQUESTED /
COMMENTED decisions separately from the full review list.

Output: data/{author}_reviewed_prs.json

Usage:
    python3 scripts/fetch_reviewed_prs.py
    python3 scripts/fetch_reviewed_prs.py --since 2025-05-28
    python3 scripts/fetch_reviewed_prs.py --author <github-login>
    python3 scripts/fetch_reviewed_prs.py --org my-company
    python3 scripts/fetch_reviewed_prs.py --output path/to/custom.json
"""

import argparse
import json
from pathlib import Path

from pr_utils import START_DATE, current_user, discover_repos, fetch_prs_for_numbers, search_pr_numbers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since",  default=START_DATE)
    parser.add_argument("--author", default=None, help="GitHub username (defaults to current authenticated user)")
    parser.add_argument("--org",    default=None, help="Limit results to this GitHub org (e.g. my-company). Omit to include all orgs.")
    parser.add_argument("--output", default=None, help="Output path (default: data/{author}_reviewed_prs.json)")
    parser.add_argument("--force",  action="store_true", help="Re-fetch even if output already exists")
    args = parser.parse_args()

    author = args.author or current_user()
    output_path = Path(args.output or f"data/{author}_reviewed_prs.json")

    if output_path.exists() and not args.force:
        print(f"Cache hit: {output_path} already exists. Pass --force to re-fetch.")
        return

    print(f"Fetching PRs reviewed by: {author}  (since {args.since})")

    print("Discovering repos...", end=" ", flush=True)
    repos = discover_repos(f"reviewed-by:{author}+-author:{author}", args.since, org=args.org)
    print(f"{len(repos)} repos found: {', '.join(r.split('/')[1] for r in repos)}")

    all_numbers: list[tuple[str, int]] = []
    for repo in repos:
        print(f"  Searching {repo} ...", end=" ", flush=True)
        numbers = search_pr_numbers(
            f"reviewed-by:{author}+-author:{author}+repo:{repo}",
            args.since,
        )
        print(f"{len(numbers)} found")
        all_numbers.extend(numbers)

    print(f"\nFetching details for {len(all_numbers)} PRs...")
    prs = fetch_prs_for_numbers(all_numbers, label="fetching")

    for pr in prs:
        pr["your_reviews"] = [r for r in pr.get("reviews", []) if r["author"] == author]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(prs, indent=2))

    approved = sum(1 for pr in prs if any(r["state"] == "APPROVED" for r in pr["your_reviews"]))
    changes  = sum(1 for pr in prs if any(r["state"] == "CHANGES_REQUESTED" for r in pr["your_reviews"]))
    commented = sum(
        1 for pr in prs
        if pr["your_reviews"] and all(r["state"] == "COMMENTED" for r in pr["your_reviews"])
    )

    print(f"Total: {len(prs)} PRs reviewed — {approved} approved, {changes} changes requested, {commented} commented only")
    print(f"Written to: {output_path}")


if __name__ == "__main__":
    main()
