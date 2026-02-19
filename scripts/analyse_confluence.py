#!/usr/bin/env python3
"""
Analyse Confluence page contributions from data produced by fetch_confluence.py.

Shows pages created and pages edited (contributed to but not created), with titles,
spaces, and dates.

Usage:
    python3 scripts/analyse_confluence.py --author ben-kalmus
    python3 scripts/analyse_confluence.py --input data/ben-kalmus_confluence.json
    python3 scripts/analyse_confluence.py --input data/ben-kalmus_confluence.json --output data/confluence_stats.json
"""

import argparse
import json
import sys
from pathlib import Path


def fmt_int(n: int) -> str:
    return f"{n:,}"


def display(author: str, data: dict) -> None:
    created = data.get("created", [])
    contributed = data.get("contributed", [])
    total = len(created) + len(contributed)
    since = data.get("since", "")

    print(f"\n{'═' * 55}")
    print(f"  Confluence Analysis — {author}")
    if since:
        print(f"  (since {since})")
    print(f"{'═' * 55}")

    print(f"\n── Summary {'─' * 43}")
    print(f"  Pages created by you    {fmt_int(len(created)):>5}")
    print(f"  Pages edited by you     {fmt_int(len(contributed)):>5}   (others' pages)")
    print(f"  Total pages touched     {fmt_int(total):>5}")

    _print_page_list("Pages Created", created)
    _print_page_list("Pages Edited (not created by you)", contributed)

    print()


def _print_page_list(heading: str, pages: list[dict]) -> None:
    n = len(pages)
    fill = 53 - len(heading) - 2
    print(f"\n── {heading} {'─' * max(fill, 2)}  {n} pages")
    if not pages:
        print("  (none)")
        return
    print(f"  {'space':<8}  {'title':<60}  {'date'}")
    print(f"  {'─' * 8}  {'─' * 60}  {'─' * 10}")
    for p in sorted(pages, key=lambda x: x.get("created", ""), reverse=True):
        space = (p.get("space") or "")[:8]
        title = (p.get("title") or "")
        if len(title) > 60:
            title = title[:57] + "..."
        date = (p.get("created") or "")[:10]
        print(f"  {space:<8}  {title:<60}  {date}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--author",
        default=None,
        help="GitHub login (used to derive default input path)",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Confluence JSON (default: data/{author}_confluence.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Also write summary stats JSON to this path",
    )
    args = parser.parse_args()

    author = args.author

    if args.input:
        input_path = Path(args.input)
    elif author:
        input_path = Path(f"data/{author}_confluence.json")
    else:
        parser.error(
            "Pass --author <login> or --input <path> to specify which JSON to analyse."
        )

    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    data = json.loads(input_path.read_text())

    if not author:
        author = input_path.stem.removesuffix("_confluence") or "unknown"

    display(author, data)

    if args.output:
        created = data.get("created", [])
        contributed = data.get("contributed", [])
        stats = {
            "author": author,
            "since": data.get("since", ""),
            "pages_created": len(created),
            "pages_edited": len(contributed),
            "total_pages_touched": len(created) + len(contributed),
        }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stats, indent=2))
        print(f"Stats written to: {args.output}")


if __name__ == "__main__":
    main()
