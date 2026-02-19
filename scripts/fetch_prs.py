#!/usr/bin/env python3
"""
Fetch all PRs authored by a GitHub user across all relevant repos
since the employment start date.

Output: data/prs.json  — list of PR objects, each tagged with `repo`

Usage:
    python3 scripts/fetch_prs.py
    python3 scripts/fetch_prs.py --since 2025-05-28 --output data/prs.json
    python3 scripts/fetch_prs.py --author some-colleague --output data/prs_colleague.json
"""

import argparse
import json
from pathlib import Path

from pr_utils import REPOS, START_DATE, current_user, fetch_prs_for_numbers, search_pr_numbers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default=START_DATE)
    parser.add_argument("--output", default="data/prs.json")
    parser.add_argument(
        "--author",
        default=None,
        help="GitHub username (defaults to current authenticated user)",
    )
    args = parser.parse_args()

    author = args.author or current_user()
    print(f"Fetching authored PRs for: {author}  (since {args.since})")

    # Collect PR numbers across all repos
    all_numbers: list[tuple[str, int]] = []
    for repo in REPOS:
        print(f"  Searching {repo} ...", end=" ", flush=True)
        numbers = search_pr_numbers(f"author:{author}+repo:{repo}", args.since)
        print(f"{len(numbers)} found")
        all_numbers.extend(numbers)

    print(f"\nFetching details for {len(all_numbers)} PRs...")
    prs = fetch_prs_for_numbers(all_numbers, label="fetching")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(prs, indent=2))

    merged = sum(1 for pr in prs if pr["mergedAt"])
    open_  = sum(1 for pr in prs if pr["state"] == "OPEN")
    closed = sum(1 for pr in prs if pr["state"] == "CLOSED" and not pr["mergedAt"])

    print(f"Total: {len(prs)} PRs — {merged} merged, {open_} open, {closed} closed")
    print(f"Written to: {output_path}")


if __name__ == "__main__":
    main()
