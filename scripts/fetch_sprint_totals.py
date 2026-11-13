#!/usr/bin/env python3
"""
Fetch total team ticket counts and story points per sprint from the JIRA REST API.

Reads the person's JIRA tickets from fetch_jira.py to discover which sprints they worked in,
then queries JIRA for the full team's resolved tickets in each of those sprints.
Output is cached to avoid hitting the API on every analysis run.

Output: data/{name}_sprint_totals.json, where name is the email before the @
  {
    "Composition #41": {"total_tickets": 25, "total_story_points": 80.0},
    ...
  }

Usage:
    python3 scripts/fetch_sprint_totals.py
    python3 scripts/fetch_sprint_totals.py --email colleague@your-org.com --force
    python3 scripts/fetch_sprint_totals.py --sp-field customfield_10028

Auth (read from the environment or .env):
    JIRA_URL=https://your-org.atlassian.net
    JIRA_EMAIL=you@your-org.com
    JIRA_TOKEN=<your-api-token>
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from atlassian import build_auth_header, get_json, post_json, require_env, search_issues
from utils import add_email_arg, load_dotenv, name_from_email


# ── constants ─────────────────────────────────────────────────────────────────

_DEFAULT_SP_FIELD = "customfield_10016"
_SP_FIELD_NAMES = {"story points", "story point estimate", "story points estimate"}


# ── ticket helpers ────────────────────────────────────────────────────────────


def infer_project(tickets: list[dict]) -> str:
    """Return the most common Project key among tickets."""
    counts = Counter(t["Project key"] for t in tickets if t["Project key"])
    if not counts:
        print("Error: no tickets with a Project key", file=sys.stderr)
        sys.exit(1)
    return counts.most_common(1)[0][0]


def sprints_for_project(tickets: list[dict], project: str) -> list[str]:
    """Return sorted unique sprint names from tickets belonging to `project`."""
    return sorted({s for t in tickets if t["Project key"] == project for s in t["Sprints"]})


# ── story-point field discovery ───────────────────────────────────────────────


def resolve_sp_fields(
    base_url: str,
    auth_header: str,
    project: str,
    sprint: str,
    primary_field: str,
    debug: bool = False,
) -> list[str]:
    """
    Return an ordered list of SP field IDs to try per ticket.
    Starts with primary_field, then adds name-matched fields from the field registry,
    then any numeric customfield_* found on real tickets in the sprint.
    Each field is tried in order per ticket; the first non-null value wins.
    """
    seen: set[str] = set()
    candidates: list[str] = []

    def add(fid: str) -> None:
        if fid not in seen:
            seen.add(fid)
            candidates.append(fid)

    add(primary_field)

    # Name-matched candidates from the field registry
    try:
        all_fields = get_json(
            f"{base_url}/rest/api/3/field", auth_header, {}, debug=debug
        )
        if isinstance(all_fields, list):
            for field in all_fields:
                if field.get("name", "").lower() in _SP_FIELD_NAMES:
                    add(field["id"])
    except Exception:
        pass

    # Probe-discovered numeric custom fields from a sample of real tickets
    try:
        data = post_json(
            f"{base_url}/rest/api/3/search/jql",
            auth_header,
            {
                "jql": f'project="{project}" AND sprint="{sprint}" AND status=Done',
                "fields": ["*all"],
                "maxResults": 5,
            },
            debug=debug,
        )
        for issue in data.get("issues", []):
            for k, v in issue.get("fields", {}).items():
                if (
                    k.startswith("customfield_")
                    and isinstance(v, (int, float))
                    and v > 0
                ):
                    add(k)
    except Exception:
        pass

    return candidates


# ── sprint fetch ──────────────────────────────────────────────────────────────


def fetch_sprint_total(
    base_url: str,
    auth_header: str,
    project: str,
    sprint_name: str,
    sp_fields: list[str],
    debug: bool = False,
) -> dict:
    """
    Query JIRA for all Done tickets in `project` during `sprint_name`.
    Paginates automatically. Returns {"total_tickets": N, "total_story_points": F}.
    For each ticket, tries sp_fields in order and uses the first non-null value.
    """
    jql = f'project="{project}" AND sprint="{sprint_name}" AND status=Done'
    issues = search_issues(base_url, auth_header, jql, sp_fields, debug=debug)
    total_sp = 0.0
    null_sp_count = 0

    for issue in issues:
        fields = issue.get("fields", {})
        sp = next((fields[f] for f in sp_fields if fields.get(f) is not None), None)
        if sp is not None:
            total_sp += float(sp)
        else:
            null_sp_count += 1

    return {
        "total_tickets": len(issues),
        "total_story_points": round(total_sp, 1),
        "_null_sp_count": null_sp_count,
    }


# ── main ──────────────────────────────────────────────────────────────────────


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    add_email_arg(parser)
    parser.add_argument(
        "--project", default=None, help="Project key (default: the most common project in the tickets)"
    )
    parser.add_argument(
        "--sp-field",
        default=_DEFAULT_SP_FIELD,
        help=f"Story points custom field ID to try first (default: {_DEFAULT_SP_FIELD}); additional fields are auto-discovered",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="JIRA tickets JSON from fetch_jira.py (default: data/{name}_jira.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON (default: data/{name}_sprint_totals.json)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-fetch even if output already exists"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print each request URL and response body on errors",
    )
    args = parser.parse_args()

    name = name_from_email(args.email)
    input_path = Path(args.input or f"data/{name}_jira.json")
    output_path = Path(args.output or f"data/{name}_sprint_totals.json")

    if not input_path.exists():
        print(f"Error: {input_path} not found. Run: python3 scripts/fetch_jira.py --email {args.email}", file=sys.stderr)
        sys.exit(1)

    # Cache check
    if output_path.exists() and not args.force:
        print(f"Cache hit: {output_path} already exists. Pass --force to re-fetch.")
        sys.exit(0)

    base_url = require_env("JIRA_URL").rstrip("/")
    auth_header = build_auth_header()

    # Project and sprints
    tickets = json.loads(input_path.read_text())["tickets"]
    project = args.project or infer_project(tickets)
    sprints = sprints_for_project(tickets, project)

    if not sprints:
        print(
            f"No sprints found for project '{project}' in {input_path}. Nothing to fetch."
        )
        sys.exit(0)

    print(f"Project: {project}  |  {len(sprints)} sprints to fetch")

    # Resolve SP fields once upfront — tries primary field first, then any others with data
    sp_fields = resolve_sp_fields(
        base_url, auth_header, project, sprints[0], args.sp_field, debug=args.debug
    )
    print(f"SP fields: {', '.join(sp_fields)}")

    results: dict[str, dict] = {}
    total_null_sp = 0

    for i, sprint in enumerate(sprints, 1):
        print(f"\r  [{i}/{len(sprints)}] {sprint:<40}", end="", flush=True)
        result = fetch_sprint_total(
            base_url, auth_header, project, sprint, sp_fields, debug=args.debug
        )
        total_null_sp += result.pop("_null_sp_count")
        results[sprint] = result

    print()  # newline after progress

    if total_null_sp > 0:
        print(
            f"  Note: {total_null_sp} team tickets had no story points across fields {sp_fields}.",
            file=sys.stderr,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))
    print(f"Sprint totals written to: {output_path}")


if __name__ == "__main__":
    main()
