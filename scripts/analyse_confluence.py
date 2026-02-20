#!/usr/bin/env python3
"""
Analyse Confluence page contributions from data produced by fetch_confluence.py.

Sections:
  Summary · By Space · By Content Type · Activity Timeline ·
  Created Page Versions · Pages Created · Pages Edited

Usage:
    python3 scripts/analyse_confluence.py --author ben-kalmus
    python3 scripts/analyse_confluence.py --input data/ben-kalmus_confluence.json
    python3 scripts/analyse_confluence.py --input data/ben-kalmus_confluence.json --output data/confluence_stats.json
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from utils import bar, fmt_int, pct


def space_label(key: str) -> tuple[str, str]:
    if key.startswith("~"):
        return "Personal", "personal"
    return key, "team"


def infer_content_type(title: str, space: str) -> str:
    if space.upper() == "RFC" or re.search(r"\bRFC\b", title):
        return "RFC"
    if re.match(r"DD\s*[-–]", title) or re.search(r"design\s+doc", title, re.IGNORECASE):
        return "Design Doc"
    if re.search(r"\bimplement", title, re.IGNORECASE):
        return "Implementation"
    if re.search(r"\bflowchart\b|\bdiagram\b", title, re.IGNORECASE):
        return "Flowchart / Diagram"
    return "Other"


def ym(date_str: str) -> str:
    return date_str[:7] if date_str and len(date_str) >= 7 else ""


# ── display ───────────────────────────────────────────────────────────────────


def _section(heading: str, fill: int = 53) -> None:
    pad = fill - len(heading) - 3
    print(f"\n── {heading} {'─' * max(pad, 2)}")


def display(author: str, data: dict) -> None:
    created = data.get("created", [])
    contributed = data.get("contributed", [])
    all_pages = created + contributed
    total = len(all_pages)
    since = data.get("since", "")

    print(f"\n{'═' * 55}")
    print(f"  Confluence Analysis — {author}")
    if since:
        print(f"  (since {since})")
    print(f"{'═' * 55}")

    # ── Summary ───────────────────────────────────────────────
    _section("Summary")
    print(f"  Pages created by you    {fmt_int(len(created)):>5}")
    print(f"  Pages edited by you     {fmt_int(len(contributed)):>5}   (others' pages)")
    print(f"  Total pages touched     {fmt_int(total):>5}")

    # ── By Space ──────────────────────────────────────────────
    space_counts: Counter = Counter()
    for p in all_pages:
        label, _ = space_label(p.get("space", ""))
        space_counts[label] += 1

    unique_spaces = len({
        p.get("space", "") for p in all_pages if not p.get("space", "").startswith("~")
    }) + (1 if any(p.get("space", "").startswith("~") for p in all_pages) else 0)

    _section(f"By Space  ({unique_spaces} spaces)")
    for sp, n in space_counts.most_common():
        kind = "personal" if sp == "Personal" else "team"
        b = bar(n / total)
        print(f"  {sp:<12} ({kind:<8})  {n:>3}  {pct(n, total):>4}  {b}")

    # ── By Content Type ────────────────────────────────────────
    type_counts: Counter = Counter(
        infer_content_type(p.get("title", ""), p.get("space", "")) for p in all_pages
    )
    _section("By Content Type")
    for ctype, n in type_counts.most_common():
        b = bar(n / total)
        print(f"  {ctype:<22}  {n:>3}  {pct(n, total):>4}  {b}")

    # ── Activity Timeline ──────────────────────────────────────
    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"created": 0, "edited": 0})
    for p in created:
        m = ym(p.get("created", ""))
        if m:
            monthly[m]["created"] += 1
    for p in contributed:
        m = ym(p.get("last_modified", "") or p.get("created", ""))
        if m:
            monthly[m]["edited"] += 1

    if monthly:
        _section("Activity Timeline")
        max_activity = max(v["created"] + v["edited"] for v in monthly.values())
        print(f"  {'month':<10}  {'created':>7}  {'edited':>6}   activity")
        print(f"  {'─' * 10}  {'─' * 7}  {'─' * 6}   {'─' * 20}")
        for month in sorted(monthly):
            v = monthly[month]
            total_month = v["created"] + v["edited"]
            b = bar(total_month / max_activity if max_activity else 0)
            print(f"  {month:<10}  {v['created']:>7}  {v['edited']:>6}   {b}  {total_month}")

    # ── Created Page Versions ──────────────────────────────────
    versions = [
        (p.get("version_number") or 0, p.get("title", ""), p.get("last_modified", ""))
        for p in created
        if p.get("version_number") is not None
    ]
    if versions:
        v_nums = [v for v, _, _ in versions]
        _section("Created Page Versions")
        print(f"  Mean versions/page     {mean(v_nums):.1f}")
        print(f"  Median                 {median(v_nums):.1f}")
        print(f"  Max                    {max(v_nums)}")
        drafts = sum(1 for v in v_nums if v <= 2)
        if drafts:
            print(f"  Still at v1-2 (draft)  {drafts}")
        print()
        print(f"  {'v':>3}  {'last modified':<13}  title")
        print(f"  {'─' * 3}  {'─' * 13}  {'─' * 55}")
        for v_num, title, last_mod in sorted(versions, reverse=True):
            short = title[:55] + "..." if len(title) > 55 else title
            print(f"  {v_num:>3}  {last_mod:<13}  {short}")

    # ── Page Lists ────────────────────────────────────────────
    _print_page_list("Pages Created", created, show_version=True)
    _print_page_list("Pages Edited (not created by you)", contributed, show_version=False)

    print()


def _print_page_list(heading: str, pages: list[dict], show_version: bool = False) -> None:
    n = len(pages)
    fill = 53 - len(heading) - 2
    print(f"\n── {heading} {'─' * max(fill, 2)}  {n} pages")
    if not pages:
        print("  (none)")
        return

    if show_version:
        print(f"  {'space':<8}  {'v':>3}  {'title':<58}  {'date'}")
        print(f"  {'─' * 8}  {'─' * 3}  {'─' * 58}  {'─' * 10}")
    else:
        print(f"  {'space':<8}  {'title':<60}  {'date'}")
        print(f"  {'─' * 8}  {'─' * 60}  {'─' * 10}")

    sort_field = "created" if show_version else "last_modified"
    for p in sorted(pages, key=lambda x: x.get(sort_field) or "", reverse=True):
        space = (p.get("space") or "")[:8]
        title = p.get("title") or ""
        date = (p.get("created") or "")[:10]

        if show_version:
            v = p.get("version_number") or ""
            if len(title) > 58:
                title = title[:55] + "..."
            print(f"  {space:<8}  {v!s:>3}  {title:<58}  {date}")
        else:
            last_mod = (p.get("last_modified") or date)[:10]
            if len(title) > 60:
                title = title[:57] + "..."
            print(f"  {space:<8}  {title:<60}  {last_mod}")


# ── main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--author", default=None, help="GitHub login (used to derive default input path)")
    parser.add_argument("--input", default=None, help="Confluence JSON (default: data/{author}_confluence.json)")
    parser.add_argument("--output", default=None, help="Also write summary stats JSON to this path")
    args = parser.parse_args()

    author = args.author

    if args.input:
        input_path = Path(args.input)
    elif author:
        input_path = Path(f"data/{author}_confluence.json")
    else:
        raise SystemExit("Pass --author <login> or --input <path> to specify which JSON to analyse.")

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    data = json.loads(input_path.read_text())

    if not author:
        author = input_path.stem.removesuffix("_confluence") or "unknown"

    display(author, data)

    if args.output:
        created = data.get("created", [])
        contributed = data.get("contributed", [])
        type_counts = Counter(
            infer_content_type(p.get("title", ""), p.get("space", ""))
            for p in created + contributed
        )
        space_counts: Counter = Counter()
        for p in created + contributed:
            label, _ = space_label(p.get("space", ""))
            space_counts[label] += 1
        v_nums = [p.get("version_number") for p in created if p.get("version_number") is not None]
        stats = {
            "author": author,
            "since": data.get("since", ""),
            "pages_created": len(created),
            "pages_edited": len(contributed),
            "total_pages_touched": len(created) + len(contributed),
            "by_space": dict(space_counts.most_common()),
            "by_content_type": dict(type_counts.most_common()),
            "version_mean": round(mean(v_nums), 1) if v_nums else None,
            "version_max": max(v_nums) if v_nums else None,
        }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stats, indent=2))
        print(f"Stats written to: {args.output}")


if __name__ == "__main__":
    main()
