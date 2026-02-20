#!/usr/bin/env python3
"""
Export analysis results as a Markdown document suitable for pasting into
Confluence, Notion, GitHub, or any Markdown-capable viewer.

Reads from cached data files in data/. Run fetch + analyse scripts first,
or use collect_author.sh --jira to populate everything in one go.

Usage:
    python3 scripts/export_markdown.py --author ben-kalmus
    python3 scripts/export_markdown.py --author ben-kalmus --output review.md
    python3 scripts/export_markdown.py --author ben-kalmus --since 2025-05-28
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from analyse_prs import analyse_authored, analyse_reviewed
from analyse_jira import analyse_jira as _analyse_jira
from utils import fmt_duration, fmt_int, pct


# ── Markdown primitives ───────────────────────────────────────────────────────


def h(level: int, text: str) -> str:
    return f"\n{'#' * level} {text}\n"


def table(headers: list[str], rows: list[list]) -> str:
    lines = [
        "| " + " | ".join(str(c) for c in headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines) + "\n"


def kv(pairs: list[tuple]) -> str:
    return table(["Metric", "Value"], [[k, v] for k, v in pairs])


def hr() -> str:
    return "\n---\n"


# ── Section builders ──────────────────────────────────────────────────────────


def section_prs(prs_path: Path, reviewed_path: Path, author: str) -> str:
    if not prs_path.exists():
        return ""

    prs = json.loads(prs_path.read_text())
    prs = [pr for pr in prs if pr.get("author") == author]
    authored = analyse_authored(prs, author)

    reviewed_stats = None
    if reviewed_path and reviewed_path.exists():
        reviewed_prs = json.loads(reviewed_path.read_text())
        reviewed_stats = analyse_reviewed(reviewed_prs, author)

    t   = authored["totals"]
    c   = authored["churn"]
    ttm = authored["time_to_merge_days"]
    out = []

    out.append(h(2, "GitHub Pull Requests"))

    out.append(h(3, "Summary"))
    out.append(kv([
        ("Total PRs",   fmt_int(t["prs"])),
        ("Merged",      f"{fmt_int(t['merged'])} ({pct(t['merged'], t['prs'])})"),
        ("Open",        fmt_int(t["open"])),
        ("Closed",      fmt_int(t["closed"])),
        ("Draft",       fmt_int(t["draft"])),
    ]))

    out.append(h(3, "Code Churn"))
    out.append(kv([
        ("Additions",      f"+{fmt_int(c['additions'])}"),
        ("Deletions",      f"-{fmt_int(c['deletions'])}"),
        ("Net",            f"{'+' if c['net'] >= 0 else ''}{fmt_int(c['net'])}"),
        ("Total churn",    f"{fmt_int(c['total'])} lines"),
        ("Files changed",  fmt_int(c["files"])),
        ("Per-PR average", f"+{c['avg_additions_per_pr']} / -{c['avg_deletions_per_pr']} lines, {c['avg_files_per_pr']} files"),
    ]))

    if ttm["mean"] is not None:
        out.append(h(3, "Time to Merge"))
        out.append(kv([
            ("Mean",    fmt_duration(ttm["mean"])),
            ("Median",  fmt_duration(ttm["median"])),
            ("Fastest", fmt_duration(ttm["min"])),
            ("Slowest", fmt_duration(ttm["max"])),
        ]))

    out.append(h(3, "PR Size Distribution"))
    size_rows = []
    for bucket in ["XS (≤50)", "S (51-200)", "M (201-500)", "L (501-1000)", "XL (>1000)"]:
        n = authored["size_distribution"].get(bucket, 0)
        size_rows.append([bucket, n, pct(n, t["prs"])])
    out.append(table(["Size", "Count", "%"], size_rows))

    out.append(h(3, "By Repository"))
    repo_rows = [
        [repo.split("/")[-1], s["prs"], f"+{fmt_int(s['additions'])}", f"-{fmt_int(s['deletions'])}"]
        for repo, s in authored["repos"].items()
    ]
    out.append(table(["Repository", "PRs", "+Lines", "-Lines"], repo_rows))

    out.append(h(3, "How Your PRs Were Received"))
    out.append(table(
        ["Decision", "Count"],
        [[d, n] for d, n in authored["received_decisions"].items()],
    ))

    out.append(h(3, "Who Reviewed Your Work"))
    out.append(table(
        ["Reviewer", "Review messages"],
        [[r, n] for r, n in authored["top_reviewers_of_your_work"].items()],
    ))

    if reviewed_stats:
        rv = reviewed_stats
        out.append(h(3, "Your Review Activity"))
        out.append(kv([("PRs reviewed for others", rv["total_prs_reviewed"])]))

        out.append(h(4, "Verdicts Given"))
        out.append(table(
            ["Verdict", "Count"],
            [[s, n] for s, n in rv["review_verdicts_given"].items()],
        ))

        out.append(h(4, "Authors Reviewed"))
        out.append(table(
            ["Author", "PRs"],
            [[a, n] for a, n in rv["authors_reviewed"].items()],
        ))

    return "\n".join(out)


def section_jira(jira_path: Path, sprint_totals_path: Path, author: str) -> str:
    if not jira_path.exists():
        return ""

    with jira_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assignee_counts: Counter = Counter(
        r.get("Assignee", "").strip() for r in rows if r.get("Assignee", "").strip()
    )
    jira_name = assignee_counts.most_common(1)[0][0] if assignee_counts else ""

    sprint_totals: dict | None = None
    if sprint_totals_path and sprint_totals_path.exists():
        sprint_totals = json.loads(sprint_totals_path.read_text())

    stats = _analyse_jira(rows, jira_name)
    t  = stats["totals"]
    sp = stats["story_points"]
    ct = stats["cycle_time_days"]
    out = []

    out.append(h(2, "JIRA Tickets"))

    out.append(h(3, "Summary"))
    summary_rows = [
        ("Total tickets",     fmt_int(t["tickets"])),
        ("Assigned to you",   f"{fmt_int(t['assigned'])} ({pct(t['assigned'], t['tickets'])})"),
        ("Reported by you",   f"{fmt_int(t['reported'])} ({pct(t['reported'], t['tickets'])})"),
        ("Resolved",          f"{fmt_int(t['resolved'])} ({pct(t['resolved'], t['assigned'])})"),
        ("Bugs",              f"{fmt_int(t['bugs'])} ({t['bug_rate_pct']}%)"),
    ]
    if t["both"]:
        summary_rows.insert(3, ("Both assigned and reported", fmt_int(t["both"])))
    out.append(kv(summary_rows))
    out.append("*All sections below: assigned tickets only.*\n")

    out.append(h(3, "By Issue Type"))
    out.append(table(
        ["Type", "Count", "%"],
        [[tp, n, pct(n, t["assigned"])] for tp, n in stats["by_type"].items()],
    ))

    out.append(h(3, "By Priority"))
    out.append(table(
        ["Priority", "Count", "%"],
        [[p, n, pct(n, t["assigned"])] for p, n in stats["by_priority"].items()],
    ))

    if len(stats["by_project"]) > 1:
        out.append(h(3, "By Project"))
        out.append(table(
            ["Project", "Count", "%"],
            [[p, n, pct(n, t["assigned"])] for p, n in stats["by_project"].items()],
        ))

    out.append(h(3, "Story Points"))
    sp_rows = [("Total", fmt_int(sp["total"]))]
    if sp["mean_per_ticket"] is not None:
        sp_rows += [
            ("Mean / ticket", sp["mean_per_ticket"]),
            ("Median",        sp["median_per_ticket"]),
            ("Min",           sp["min"]),
            ("Max",           sp["max"]),
        ]
    if sp["missing_count"]:
        sp_rows.append(("Missing on", f"{sp['missing_count']} tickets"))
    out.append(kv(sp_rows))

    if ct["mean"] is not None:
        out.append(h(3, "Cycle Time (created → resolved)"))
        out.append(kv([
            ("Mean",    fmt_duration(ct["mean"])),
            ("Median",  fmt_duration(ct["median"])),
            ("Fastest", fmt_duration(ct["min"])),
            ("Slowest", fmt_duration(ct["max"])),
            ("Sample",  f"{ct['count']} resolved tickets"),
        ]))

    out.append(h(3, "Epics / Initiatives"))
    epic_rows = [
        [e if e != "— (no epic)" else "*(no epic)*", n]
        for e, n in stats["epics"].items()
    ]
    out.append(table(["Epic", "Tickets"], epic_rows))

    out.append(h(3, "Sprint Contribution"))
    sprints = stats["sprints"]
    if sprint_totals:
        sprint_rows = []
        for sprint, s in sprints.items():
            pts = s["story_points"] if s["story_points"] else "—"
            if sprint in sprint_totals:
                tot = sprint_totals[sprint]
                total_t = tot["total_tickets"]
                sprint_rows.append([sprint, s["tickets"], total_t, pct(s["tickets"], total_t), pts])
            else:
                sprint_rows.append([sprint, s["tickets"], "—", "—", pts])
        out.append(table(["Sprint", "Your tickets", "Team total", "Tickets %", "Your pts"], sprint_rows))
    else:
        out.append(table(
            ["Sprint", "Tickets", "Story points"],
            [[s, v["tickets"], v["story_points"]] for s, v in sprints.items()],
        ))

    return "\n".join(out)


def section_confluence(confluence_path: Path) -> str:
    if not confluence_path.exists():
        return ""

    data = json.loads(confluence_path.read_text())
    created    = data.get("created", [])
    contributed = data.get("contributed", [])
    all_pages  = created + contributed
    total      = len(all_pages)
    since      = data.get("since", "")
    out = []

    out.append(h(2, "Confluence Contributions"))
    if since:
        out.append(f"*Since {since}*\n")

    out.append(h(3, "Summary"))
    out.append(kv([
        ("Pages created by you",  len(created)),
        ("Pages edited by you",   len(contributed)),
        ("Total pages touched",   total),
    ]))

    # By space
    space_counts: Counter = Counter()
    for p in all_pages:
        key = p.get("space", "")
        label = "Personal" if key.startswith("~") else key
        space_counts[label] += 1

    out.append(h(3, "By Space"))
    out.append(table(
        ["Space", "Type", "Count", "%"],
        [
            [sp, "personal" if sp == "Personal" else "team", n, pct(n, total)]
            for sp, n in space_counts.most_common()
        ],
    ))

    # By content type
    import re

    def infer_type(title: str, space: str) -> str:
        if space.upper() == "RFC" or re.search(r"\bRFC\b", title):
            return "RFC"
        if re.match(r"DD\s*[-–]", title) or re.search(r"design\s+doc", title, re.IGNORECASE):
            return "Design Doc"
        if re.search(r"\bimplement", title, re.IGNORECASE):
            return "Implementation"
        if re.search(r"\bflowchart\b|\bdiagram\b", title, re.IGNORECASE):
            return "Flowchart / Diagram"
        return "Other"

    type_counts: Counter = Counter(
        infer_type(p.get("title", ""), p.get("space", "")) for p in all_pages
    )
    out.append(h(3, "By Content Type"))
    out.append(table(
        ["Type", "Count", "%"],
        [[ct, n, pct(n, total)] for ct, n in type_counts.most_common()],
    ))

    # Activity timeline
    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"created": 0, "edited": 0})
    for p in created:
        m = p.get("created", "")[:7]
        if m:
            monthly[m]["created"] += 1
    for p in contributed:
        m = (p.get("last_modified") or p.get("created", ""))[:7]
        if m:
            monthly[m]["edited"] += 1

    if monthly:
        out.append(h(3, "Activity Timeline"))
        timeline_rows = [
            [month, v["created"], v["edited"], v["created"] + v["edited"]]
            for month, v in sorted(monthly.items())
        ]
        out.append(table(["Month", "Created", "Edited", "Total"], timeline_rows))

    # Version stats for created pages
    versions = [(p.get("version_number") or 0, p) for p in created if p.get("version_number")]
    if versions:
        v_nums = [v for v, _ in versions]
        out.append(h(3, "Created Page Versions"))
        from statistics import mean, median
        out.append(kv([
            ("Mean versions / page", f"{mean(v_nums):.1f}"),
            ("Median",               f"{median(v_nums):.1f}"),
            ("Max",                  max(v_nums)),
            ("Still at v1-2 (draft)", sum(1 for v in v_nums if v <= 2)),
        ]))

    # Pages created
    out.append(h(3, f"Pages Created ({len(created)})"))
    if created:
        created_rows = [
            [
                p.get("space", "")[:8],
                p.get("version_number", ""),
                p.get("title", ""),
                p.get("created", "")[:10],
            ]
            for p in sorted(created, key=lambda x: x.get("created", ""), reverse=True)
        ]
        out.append(table(["Space", "v", "Title", "Date"], created_rows))

    # Pages edited
    out.append(h(3, f"Pages Edited — others' pages ({len(contributed)})"))
    if contributed:
        edited_rows = [
            [
                p.get("space", "")[:8],
                p.get("title", ""),
                (p.get("last_modified") or p.get("created", ""))[:10],
            ]
            for p in sorted(contributed, key=lambda x: x.get("last_modified") or x.get("created", ""), reverse=True)
        ]
        out.append(table(["Space", "Title", "Last modified"], edited_rows))

    return "\n".join(out)


# ── main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--author",  required=True, help="GitHub login")
    parser.add_argument("--since",   default=None,  help="Review period start date (display only)")
    parser.add_argument("--output",  default=None,  help="Output path (default: data/{author}_review.md)")
    args = parser.parse_args()

    author      = args.author
    data_dir    = Path("data")
    output_path = Path(args.output or f"data/{author}_review.md")

    since = args.since or ""
    today = str(date.today())

    sections = []

    # Header
    period = f"{since} – {today}" if since else today
    sections.append(f"# Annual Review — {author}\n")
    sections.append(f"*Generated: {today}*  \n*Period: {period}*\n")

    # GitHub PRs
    pr_section = section_prs(
        prs_path      = data_dir / f"{author}_prs.json",
        reviewed_path = data_dir / f"{author}_reviewed_prs.json",
        author        = author,
    )
    if pr_section:
        sections.append(hr())
        sections.append(pr_section)
    else:
        print(f"Note: {data_dir}/{author}_prs.json not found — skipping PR section.")

    # JIRA
    jira_section = section_jira(
        jira_path          = data_dir / f"{author}_jira.csv",
        sprint_totals_path = data_dir / f"{author}_sprint_totals.json",
        author             = author,
    )
    if jira_section:
        sections.append(hr())
        sections.append(jira_section)
    else:
        print(f"Note: {data_dir}/{author}_jira.csv not found — skipping JIRA section.")

    # Confluence
    conf_section = section_confluence(
        confluence_path = data_dir / f"{author}_confluence.json",
    )
    if conf_section:
        sections.append(hr())
        sections.append(conf_section)
    else:
        print(f"Note: {data_dir}/{author}_confluence.json not found — skipping Confluence section.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(sections))
    print(f"Markdown written to: {output_path}")


if __name__ == "__main__":
    main()
