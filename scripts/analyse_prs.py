#!/usr/bin/env python3
"""
Analyse PR statistics from fetched PR JSON files.

Produces a summary covering: PR counts by state, code churn, file changes,
repo breakdown, how your PRs were received, your review activity, and
time-to-merge — designed to be run for the primary author and peers for
direct comparison.

Usage:
    python3 scripts/analyse_prs.py
    python3 scripts/analyse_prs.py --input data/prs.json --reviewed-input data/reviewed_prs.json
    python3 scripts/analyse_prs.py --input data/prs_peer.json --reviewed-input data/reviewed_prs_peer.json --author peer-login
    python3 scripts/analyse_prs.py --output data/pr_stats.json   # also write JSON
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median


# ── helpers ──────────────────────────────────────────────────────────────────

def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def days_between(a: str | None, b: str | None) -> float | None:
    dt_a, dt_b = parse_dt(a), parse_dt(b)
    if dt_a and dt_b:
        return (dt_b - dt_a).total_seconds() / 86400
    return None


def pct(n: int, total: int) -> str:
    return f"{n / total * 100:.0f}%" if total else "0%"


def fmt_int(n: int) -> str:
    return f"{n:,}"


# ── core analysis ─────────────────────────────────────────────────────────────

def analyse_authored(prs: list[dict], author: str) -> dict:
    """Stats derived from PRs where this person is the author."""
    total = len(prs)
    merged = [pr for pr in prs if pr.get("mergedAt")]
    open_  = [pr for pr in prs if pr["state"] == "OPEN"]
    closed = [pr for pr in prs if pr["state"] == "CLOSED" and not pr.get("mergedAt")]
    drafts = [pr for pr in prs if pr.get("isDraft")]

    # Code churn
    additions = sum(pr.get("additions", 0) or 0 for pr in prs)
    deletions = sum(pr.get("deletions", 0) or 0 for pr in prs)
    churn     = additions + deletions
    net       = additions - deletions
    files     = sum(pr.get("changedFiles", 0) or 0 for pr in prs)

    # Per-PR size buckets
    def size_bucket(pr):
        c = (pr.get("additions") or 0) + (pr.get("deletions") or 0)
        if c <= 50:   return "XS (≤50)"
        if c <= 200:  return "S (51-200)"
        if c <= 500:  return "M (201-500)"
        if c <= 1000: return "L (501-1000)"
        return "XL (>1000)"

    size_dist = Counter(size_bucket(pr) for pr in prs)

    # Time to merge (calendar days)
    ttm = [
        d for pr in merged
        if (d := days_between(pr.get("createdAt"), pr.get("mergedAt"))) is not None
    ]

    # Repo breakdown
    repo_stats = defaultdict(lambda: {"prs": 0, "additions": 0, "deletions": 0, "files": 0})
    for pr in prs:
        r = pr["repo"]
        repo_stats[r]["prs"]       += 1
        repo_stats[r]["additions"] += pr.get("additions", 0) or 0
        repo_stats[r]["deletions"] += pr.get("deletions", 0) or 0
        repo_stats[r]["files"]     += pr.get("changedFiles", 0) or 0

    # How your PRs were received by reviewers (reviewDecision on merged PRs)
    received_decisions = Counter(pr.get("reviewDecision") or "NONE" for pr in merged)

    # Who reviewed your work most (excluding self)
    reviewer_counts: Counter = Counter()
    for pr in prs:
        for r in pr.get("reviews", []):
            if r["author"] != author:
                reviewer_counts[r["author"]] += 1

    return {
        "totals": {
            "prs":    total,
            "merged": len(merged),
            "open":   len(open_),
            "closed": len(closed),
            "draft":  len(drafts),
        },
        "churn": {
            "additions": additions,
            "deletions": deletions,
            "net":       net,
            "total":     churn,
            "files":     files,
            "avg_additions_per_pr": round(additions / total, 1) if total else 0,
            "avg_deletions_per_pr": round(deletions / total, 1) if total else 0,
            "avg_files_per_pr":     round(files / total, 1) if total else 0,
        },
        "size_distribution": dict(size_dist),
        "time_to_merge_days": {
            "mean":   round(mean(ttm), 1) if ttm else None,
            "median": round(median(ttm), 1) if ttm else None,
            "min":    round(min(ttm), 1) if ttm else None,
            "max":    round(max(ttm), 1) if ttm else None,
        },
        "repos": {
            repo: dict(s)
            for repo, s in sorted(repo_stats.items(), key=lambda x: -x[1]["prs"])
        },
        "received_decisions": dict(received_decisions),
        "top_reviewers_of_your_work": dict(reviewer_counts.most_common(10)),
    }


def analyse_reviewed(reviewed_prs: list[dict], reviewer: str) -> dict:
    """Stats derived from PRs where this person acted as reviewer."""
    total = len(reviewed_prs)

    # Decisions this person gave (from your_reviews field)
    given_decisions: Counter = Counter()
    for pr in reviewed_prs:
        for r in pr.get("your_reviews", []):
            given_decisions[r["state"]] += 1

    # PRs grouped by the verdict given (use the strongest verdict per PR)
    verdict_order = {"APPROVED": 3, "CHANGES_REQUESTED": 2, "COMMENTED": 1}
    prs_by_verdict: Counter = Counter()
    for pr in reviewed_prs:
        if not pr.get("your_reviews"):
            continue
        strongest = max(pr["your_reviews"], key=lambda r: verdict_order.get(r["state"], 0))
        prs_by_verdict[strongest["state"]] += 1

    # Authors whose PRs you reviewed most
    reviewed_authors: Counter = Counter()
    for pr in reviewed_prs:
        if pr.get("author") and pr["author"] != reviewer:
            reviewed_authors[pr["author"]] += 1

    # Repos where you reviewed
    reviewed_repos = Counter(pr["repo"] for pr in reviewed_prs)

    return {
        "total_prs_reviewed": total,
        "review_verdicts_given": dict(given_decisions),
        "prs_by_strongest_verdict": dict(prs_by_verdict),
        "authors_reviewed": dict(reviewed_authors.most_common(10)),
        "repos_reviewed": dict(reviewed_repos.most_common()),
    }


# ── display ───────────────────────────────────────────────────────────────────

def display(author: str, authored: dict, reviewed: dict | None) -> None:
    t   = authored["totals"]
    c   = authored["churn"]
    ttm = authored["time_to_merge_days"]

    print(f"\n{'═' * 55}")
    print(f"  PR Analysis — {author}")
    print(f"{'═' * 55}")

    print(f"\n── PR Counts {'─' * 42}")
    print(f"  Total        {fmt_int(t['prs'])}")
    print(f"  Merged       {fmt_int(t['merged'])}  ({pct(t['merged'], t['prs'])})")
    print(f"  Open         {fmt_int(t['open'])}")
    print(f"  Closed       {fmt_int(t['closed'])}")
    if t["draft"]:
        print(f"  Draft        {fmt_int(t['draft'])}")

    print(f"\n── Code Churn {'─' * 41}")
    print(f"  Additions    +{fmt_int(c['additions'])}")
    print(f"  Deletions    -{fmt_int(c['deletions'])}")
    print(f"  Net          {'+' if c['net'] >= 0 else ''}{fmt_int(c['net'])}")
    print(f"  Total churn  {fmt_int(c['total'])} lines")
    print(f"  Files        {fmt_int(c['files'])} changed")
    print(f"  Per PR avg   +{c['avg_additions_per_pr']} / -{c['avg_deletions_per_pr']} lines, {c['avg_files_per_pr']} files")

    print(f"\n── PR Size Distribution {'─' * 31}")
    for bucket in ["XS (≤50)", "S (51-200)", "M (201-500)", "L (501-1000)", "XL (>1000)"]:
        n = authored["size_distribution"].get(bucket, 0)
        print(f"  {bucket:<15} {n:>3}  {'█' * n}")

    if ttm["mean"] is not None:
        print(f"\n── Time to Merge {'─' * 38}")
        print(f"  Mean         {ttm['mean']} days")
        print(f"  Median       {ttm['median']} days")
        print(f"  Fastest      {ttm['min']} days")
        print(f"  Slowest      {ttm['max']} days")

    print(f"\n── Repositories {'─' * 39}")
    for repo, s in authored["repos"].items():
        short = repo.split("/")[-1]
        print(f"  {short:<35} {s['prs']:>3} PRs  +{fmt_int(s['additions'])} / -{fmt_int(s['deletions'])}")

    print(f"\n── How Your PRs Were Received (merged) {'─' * 16}")
    for decision, n in authored["received_decisions"].items():
        print(f"  {decision:<25} {n}")

    print(f"\n── Who Reviewed Your Work {'─' * 29}")
    for reviewer, n in authored["top_reviewers_of_your_work"].items():
        print(f"  {reviewer:<30} {n} reviews")

    if reviewed:
        rv = reviewed
        print(f"\n── Your Review Activity {'─' * 31}")
        print(f"  PRs reviewed for others   {rv['total_prs_reviewed']}")
        print()
        print(f"  Verdicts given:")
        for state, n in rv["review_verdicts_given"].items():
            print(f"    {state:<25} {n} times")
        print()
        print(f"  Per PR (strongest verdict):")
        for state, n in rv["prs_by_strongest_verdict"].items():
            print(f"    {state:<25} {n} PRs")
        print()
        print(f"  Authors you reviewed most:")
        for a, n in rv["authors_reviewed"].items():
            print(f"    {a:<30} {n} PRs")

    print()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",          default="data/prs.json",          help="Authored PRs JSON")
    parser.add_argument("--reviewed-input", default="data/reviewed_prs.json", help="Reviewed PRs JSON")
    parser.add_argument("--author",         default=None,                      help="Filter to this author login")
    parser.add_argument("--output",         default=None,                      help="Also write stats JSON to this path")
    args = parser.parse_args()

    prs = json.loads(Path(args.input).read_text())

    # Infer author from data if not supplied
    if args.author:
        author = args.author
        prs = [pr for pr in prs if pr.get("author") == author]
    else:
        authors = {pr.get("author") for pr in prs if pr.get("author")}
        if len(authors) == 1:
            author = authors.pop()
        elif len(authors) == 0:
            print("Warning: no 'author' field in PR data. Re-run fetch_prs.py or pass --author.")
            author = "unknown"
        else:
            print(f"Multiple authors found: {authors}. Pass --author to filter.")
            author = "unknown"

    authored_stats = analyse_authored(prs, author)

    # Warn if --input was customised but --reviewed-input was left as default
    default_input          = "data/prs.json"
    default_reviewed_input = "data/reviewed_prs.json"
    if args.input != default_input and args.reviewed_input == default_reviewed_input:
        print(
            f"Warning: --input is set to '{args.input}' but --reviewed-input is still "
            f"the default ('{default_reviewed_input}'). These may not match the same author. "
            f"Pass --reviewed-input to be explicit."
        )

    # Load reviewed PRs if the file exists
    reviewed_stats = None
    reviewed_path = Path(args.reviewed_input)
    if reviewed_path.exists():
        reviewed_prs = json.loads(reviewed_path.read_text())

        # Verify the reviewed file actually contains reviews by the expected author
        review_authors = {
            r["author"]
            for pr in reviewed_prs
            for r in pr.get("your_reviews", [])
        }
        if review_authors and author not in review_authors and author != "unknown":
            print(
                f"Warning: '{args.reviewed_input}' does not appear to contain reviews by '{author}'. "
                f"Found reviewer(s): {', '.join(sorted(review_authors))}. "
                f"Re-run fetch_reviewed_prs.py --author {author} to generate the correct file."
            )

        reviewed_stats = analyse_reviewed(reviewed_prs, author)
    else:
        print(f"Note: {args.reviewed_input} not found — skipping review activity section.")

    display(author, authored_stats, reviewed_stats)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"author": author, "authored": authored_stats, "reviewed": reviewed_stats}, indent=2))
        print(f"Stats written to: {args.output}")


if __name__ == "__main__":
    main()
