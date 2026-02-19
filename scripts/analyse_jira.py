#!/usr/bin/env python3
"""
Analyse JIRA ticket statistics from a stripped CSV produced by strip_jira.sh.

Produces a summary covering: ticket counts (assigned / reported / both),
issue type, priority, project, story points, cycle time, epics/initiatives,
and sprint count.

Usage:
    python3 scripts/analyse_jira.py --author ben-kalmus
    python3 scripts/analyse_jira.py --input data/ben-kalmus_jira.csv
    python3 scripts/analyse_jira.py --input data/ben-kalmus_jira.csv --output data/jira_stats.json
"""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


# ── helpers ──────────────────────────────────────────────────────────────────

def parse_dt(s: str | None) -> datetime | None:
    if not s or not s.strip():
        return None
    for fmt in ("%d/%b/%y %I:%M %p", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def days_between(a: str | None, b: str | None) -> float | None:
    dt_a, dt_b = parse_dt(a), parse_dt(b)
    if dt_a and dt_b:
        return abs((dt_b - dt_a).total_seconds()) / 86400
    return None


def fmt_int(n: int | float) -> str:
    return f"{n:,.0f}"


def pct(n: int, total: int) -> str:
    return f"{n / total * 100:.0f}%" if total else "0%"


def all_sprints(row: dict) -> list[str]:
    """Return all non-empty sprint values for a ticket."""
    sprints = []
    for col in ("Sprint", "Sprint_2", "Sprint_3"):
        val = row.get(col, "").strip()
        if val:
            sprints.append(val)
    return sprints


def story_points(row: dict) -> float | None:
    raw = row.get("Custom field (Story Points)", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# ── core analysis ─────────────────────────────────────────────────────────────

def analyse_jira(rows: list[dict], jira_name: str) -> dict:
    total = len(rows)

    # Assigned / reported breakdown — meaningful once JQL includes reporter=
    assigned  = sum(1 for r in rows if r.get("Assignee", "").strip() == jira_name)
    reported  = sum(1 for r in rows if r.get("Reporter", "").strip() == jira_name)
    both      = sum(
        1 for r in rows
        if r.get("Assignee", "").strip() == jira_name
        and r.get("Reporter", "").strip() == jira_name
    )

    # Ticket counts
    by_type     = Counter(r.get("Issue Type", "").strip() or "Unknown" for r in rows)
    by_priority = Counter(r.get("Priority", "").strip() or "Unknown" for r in rows)
    by_project  = Counter(r.get("Project key", "").strip() or "Unknown" for r in rows)

    # Story points
    sp_values  = [sp for r in rows if (sp := story_points(r)) is not None]
    sp_total   = sum(sp_values)
    sp_missing = total - len(sp_values)

    # Bug rate
    bugs = sum(1 for r in rows if r.get("Issue Type", "").strip().lower() == "bug")

    # Cycle time: Created → Resolved
    cycle_times = [
        d for r in rows
        if (d := days_between(r.get("Created"), r.get("Resolved"))) is not None
    ]

    # Epic / initiative breakdown via Parent summary
    parent_counts: Counter = Counter()
    for r in rows:
        parent = r.get("Parent summary", "").strip() or "— (no epic)"
        parent_counts[parent] += 1

    # Sprint breakdown — tickets and story points per sprint, sorted by name
    sprint_tickets: Counter = Counter()
    sprint_sp: dict[str, float] = {}
    for r in rows:
        sp = story_points(r)
        for s in all_sprints(r):
            sprint_tickets[s] += 1
            sprint_sp[s] = sprint_sp.get(s, 0.0) + (sp or 0.0)

    sprints = {
        s: {"tickets": sprint_tickets[s], "story_points": round(sprint_sp.get(s, 0), 1)}
        for s in sorted(sprint_tickets)
    }

    return {
        "totals": {
            "tickets":  total,
            "assigned": assigned,
            "reported": reported,
            "both":     both,
            "resolved": len(cycle_times),
            "bugs":     bugs,
            "bug_rate_pct": round(bugs / total * 100, 1) if total else 0,
        },
        "by_type":     dict(by_type.most_common()),
        "by_priority": dict(by_priority.most_common()),
        "by_project":  dict(by_project.most_common()),
        "story_points": {
            "total":             round(sp_total, 1),
            "mean_per_ticket":   round(mean(sp_values), 1) if sp_values else None,
            "median_per_ticket": round(median(sp_values), 1) if sp_values else None,
            "missing_count":     sp_missing,
        },
        "cycle_time_days": {
            "mean":   round(mean(cycle_times), 1) if cycle_times else None,
            "median": round(median(cycle_times), 1) if cycle_times else None,
            "min":    round(min(cycle_times), 1) if cycle_times else None,
            "max":    round(max(cycle_times), 1) if cycle_times else None,
            "count":  len(cycle_times),
        },
        "epics": dict(parent_counts.most_common()),
        "sprints": sprints,
    }


# ── display ───────────────────────────────────────────────────────────────────

def display(author: str, jira_name: str, stats: dict) -> None:
    t  = stats["totals"]
    sp = stats["story_points"]
    ct = stats["cycle_time_days"]

    print(f"\n{'═' * 55}")
    print(f"  JIRA Analysis — {author}")
    print(f"{'═' * 55}")

    print(f"\n── Ticket Counts {'─' * 37}")
    print(f"  Total            {fmt_int(t['tickets'])}")
    print(f"  Assigned to you  {fmt_int(t['assigned'])}  ({pct(t['assigned'], t['tickets'])})")
    print(f"  Reported by you  {fmt_int(t['reported'])}  ({pct(t['reported'], t['tickets'])})")
    if t["both"]:
        print(f"  Both             {fmt_int(t['both'])}")
    print(f"  Resolved         {fmt_int(t['resolved'])}  ({pct(t['resolved'], t['tickets'])})")
    print(f"  Bugs             {fmt_int(t['bugs'])}  ({t['bug_rate_pct']}%)")

    print(f"\n── By Issue Type {'─' * 37}")
    for issue_type, n in stats["by_type"].items():
        print(f"  {issue_type:<25} {n:>3}  {pct(n, t['tickets']):>4}")

    print(f"\n── By Priority {'─' * 39}")
    for priority, n in stats["by_priority"].items():
        print(f"  {priority:<25} {n:>3}  {pct(n, t['tickets']):>4}")

    print(f"\n── By Project {'─' * 40}")
    for project, n in stats["by_project"].items():
        print(f"  {project:<25} {n:>3}  {pct(n, t['tickets']):>4}")

    print(f"\n── Story Points {'─' * 38}")
    print(f"  Total            {fmt_int(sp['total'])}")
    if sp["mean_per_ticket"] is not None:
        print(f"  Mean/ticket      {sp['mean_per_ticket']}")
        print(f"  Median           {sp['median_per_ticket']}")
    if sp["missing_count"]:
        print(f"  (missing on {sp['missing_count']} tickets)")

    if ct["mean"] is not None:
        print(f"\n── Cycle Time (created → resolved) {'─' * 19}")
        print(f"  Mean             {ct['mean']} days")
        print(f"  Median           {ct['median']} days")
        print(f"  Fastest          {ct['min']} days")
        print(f"  Slowest          {ct['max']} days")
        print(f"  ({ct['count']} resolved tickets)")

    n_epics = sum(1 for e in stats["epics"] if e != "— (no epic)")
    print(f"\n── Epics / Initiatives {'─' * 31}  {n_epics} unique")
    for epic, n in stats["epics"].items():
        short = epic[:50]
        print(f"  {short:<50} {n:>3}")

    sprints = stats["sprints"]
    print(f"\n── Sprints {'─' * 43}  {len(sprints)} total")
    for sprint, s in sprints.items():
        bar = "█" * s["tickets"]
        print(f"  {sprint:<35} {s['tickets']:>2} tickets  {s['story_points']:>5.1f} pts  {bar}")

    print()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default=None, help="Stripped JIRA CSV (default: data/{author}_jira.csv)")
    parser.add_argument("--author", default=None, help="GitHub login (used to derive default input path)")
    parser.add_argument("--output", default=None, help="Also write stats JSON to this path")
    args = parser.parse_args()

    author = args.author

    if args.input:
        input_path = Path(args.input)
    elif author:
        input_path = Path(f"data/{author}_jira.csv")
    else:
        parser.error("Pass --author <login> or --input <path> to specify which CSV to analyse.")

    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    with input_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    # Infer JIRA display name from the Assignee column (e.g. "Ben Kalmus")
    assignee_counts: Counter = Counter(
        r.get("Assignee", "").strip() for r in rows if r.get("Assignee", "").strip()
    )
    jira_name = assignee_counts.most_common(1)[0][0] if assignee_counts else ""

    if not author:
        author = input_path.stem.removesuffix("_jira") or "unknown"

    stats = analyse_jira(rows, jira_name)
    display(author, jira_name, stats)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"author": author, "jira_name": jira_name, "jira": stats}, indent=2))
        print(f"Stats written to: {args.output}")


if __name__ == "__main__":
    main()
