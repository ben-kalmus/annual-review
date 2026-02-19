#!/usr/bin/env python3
"""
Fetch all PRs reviewed by a GitHub user across all relevant repos
since the employment start date.

For each PR, the top-level `your_reviews` field contains only the
reviews left by the specified reviewer — useful for showing review
activity (APPROVED / CHANGES_REQUESTED / COMMENTED) separately from
the full review list.

Output: data/reviewed_prs.json

Usage:
    python3 scripts/fetch_reviewed_prs.py
    python3 scripts/fetch_reviewed_prs.py --since 2025-05-28
    python3 scripts/fetch_reviewed_prs.py --reviewer some-colleague
"""

import argparse
import json
from pathlib import Path

from pr_utils import REPOS, START_DATE, current_user, fetch_prs_for_numbers, search_pr_numbers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default=START_DATE)
    parser.add_argument("--output", default="data/reviewed_prs.json")
    parser.add_argument(
        "--reviewer",
        default=None,
        help="GitHub username (defaults to current authenticated user)",
    )
    args = parser.parse_args()

    reviewer = args.reviewer or current_user()
    print(f"Fetching PRs reviewed by: {reviewer}  (since {args.since})")

    # Collect PR numbers across all repos, excluding own PRs
    all_numbers: list[tuple[str, int]] = []
    for repo in REPOS:
        print(f"  Searching {repo} ...", end=" ", flush=True)
        numbers = search_pr_numbers(
            f"reviewed-by:{reviewer}+-author:{reviewer}+repo:{repo}",
            args.since,
        )
        print(f"{len(numbers)} found")
        all_numbers.extend(numbers)

    print(f"\nFetching details for {len(all_numbers)} PRs...")
    prs = fetch_prs_for_numbers(all_numbers, label="fetching")

    # Attach a `your_reviews` field with only this reviewer's review actions
    for pr in prs:
        pr["your_reviews"] = [
            r for r in pr.get("reviews", [])
            if r["author"] == reviewer
        ]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(prs, indent=2))

    approved = sum(
        1 for pr in prs
        if any(r["state"] == "APPROVED" for r in pr["your_reviews"])
    )
    changes = sum(
        1 for pr in prs
        if any(r["state"] == "CHANGES_REQUESTED" for r in pr["your_reviews"])
    )
    commented = sum(
        1 for pr in prs
        if all(r["state"] == "COMMENTED" for r in pr["your_reviews"])
        and pr["your_reviews"]
    )

    print(f"Total: {len(prs)} PRs reviewed — {approved} approved, {changes} changes requested, {commented} commented only")
    print(f"Written to: {output_path}")


if __name__ == "__main__":
    main()
