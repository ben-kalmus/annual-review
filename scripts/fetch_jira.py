#!/usr/bin/env python3
"""
Fetch a person's resolved JIRA tickets from the JIRA REST API into a CSV.

Selects tickets with status Done, resolved on or after --since, where the person
is the assignee or the reporter, excluding access-request issue types.

Output: data/{name}_jira.csv, where name is the email before the @

Usage:
    python3 scripts/fetch_jira.py
    python3 scripts/fetch_jira.py --email colleague@your-org.com --since 2026-01-01 --force

Auth (read from the environment or .env):
    JIRA_URL=https://your-org.atlassian.net
    JIRA_EMAIL=you@your-org.com
    JIRA_TOKEN=<your-api-token>
"""

import argparse
import csv
import sys
from pathlib import Path

from atlassian import build_auth_header, get_json, lookup_account_id, require_env, search_issues
from utils import START_DATE, add_email_arg, load_dotenv, name_from_email, read_cache_since, warn_if_stale_cache, write_cache_since

COLUMNS = [
    "Summary",
    "Issue key",
    "Issue Type",
    "Status",
    "Status Category",
    "Project key",
    "Priority",
    "Assignee",
    "Reporter",
    "Created",
    "Resolved",
    "Labels",
    "Labels_2",
    "Sprint",
    "Sprint_2",
    "Sprint_3",
    "Custom field (Story Points)",
    "Parent key",
    "Parent summary",
    "Description",
]

BASE_FIELDS = [
    "summary",
    "issuetype",
    "status",
    "project",
    "priority",
    "assignee",
    "reporter",
    "created",
    "resolutiondate",
    "labels",
    "parent",
    "description",
]


def find_field_ids(base_url: str, auth_header: str, debug: bool = False) -> tuple[str | None, str | None]:
    """find_field_ids returns the custom field IDs named Sprint and Story Points, or None for a name JIRA does not have."""
    ids = {f.get("name", "").lower(): f["id"] for f in get_json(f"{base_url}/rest/api/2/field", auth_header, {}, debug=debug)}
    return ids.get("sprint"), ids.get("story points")


def nested(fields: dict, *path: str) -> str:
    """nested returns the string at path inside fields, or an empty string when any step is missing or null."""
    value = fields
    for key in path:
        value = (value or {}).get(key)
    return "" if value is None else str(value)


def to_row(issue: dict, sprint_field: str | None, sp_field: str | None) -> dict:
    """to_row returns the CSV row for issue, keyed by COLUMNS."""
    f = issue["fields"]
    labels = (f.get("labels") or []) + ["", ""]
    sprints = [s["name"] for s in f.get(sprint_field) or []] + ["", "", ""]
    return {
        "Summary": nested(f, "summary"),
        "Issue key": issue["key"],
        "Issue Type": nested(f, "issuetype", "name"),
        "Status": nested(f, "status", "name"),
        "Status Category": nested(f, "status", "statusCategory", "name"),
        "Project key": nested(f, "project", "key"),
        "Priority": nested(f, "priority", "name"),
        "Assignee": nested(f, "assignee", "displayName"),
        "Reporter": nested(f, "reporter", "displayName"),
        "Created": nested(f, "created"),
        "Resolved": nested(f, "resolutiondate"),
        "Labels": labels[0],
        "Labels_2": labels[1],
        "Sprint": sprints[0],
        "Sprint_2": sprints[1],
        "Sprint_3": sprints[2],
        "Custom field (Story Points)": nested(f, sp_field) if sp_field else "",
        "Parent key": nested(f, "parent", "key"),
        "Parent summary": nested(f, "parent", "fields", "summary"),
        "Description": nested(f, "description"),
    }


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    add_email_arg(parser)
    parser.add_argument("--since", default=START_DATE, help=f"Earliest resolved date YYYY-MM-DD (default: {START_DATE})")
    parser.add_argument("--output", default=None, help="Output CSV (default: data/{name}_jira.csv)")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output already exists")
    parser.add_argument("--debug", action="store_true", help="Print request URLs and error bodies")
    args = parser.parse_args()

    output_path = Path(args.output or f"data/{name_from_email(args.email)}_jira.csv")

    if output_path.exists() and not args.force:
        print(f"Cache hit: {output_path} already exists. Pass --force to re-fetch.")
        warn_if_stale_cache(output_path, read_cache_since(output_path), args.since)
        sys.exit(0)

    base_url = require_env("JIRA_URL").rstrip("/")
    auth_header = build_auth_header()

    user = "currentUser()"
    if args.email != require_env("JIRA_EMAIL"):
        account_id = lookup_account_id(base_url, auth_header, args.email, debug=args.debug)
        if not account_id:
            print(f"Error: no JIRA user found for {args.email}", file=sys.stderr)
            sys.exit(1)
        user = f'"{account_id}"'

    sprint_field, sp_field = find_field_ids(base_url, auth_header, debug=args.debug)
    jql = (
        f"(assignee = {user} OR reporter = {user}) AND status = Done"
        f' AND resolutiondate >= "{args.since}"'
        ' AND issuetype NOT IN ("Admin Access", "Access Request")'
        " ORDER BY resolutiondate ASC"
    )
    fields = BASE_FIELDS + [f for f in (sprint_field, sp_field) if f]

    print(f"Fetching JIRA tickets for: {args.email}  (since {args.since})")
    issues = search_issues(base_url, auth_header, jql, fields, debug=args.debug)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(to_row(issue, sprint_field, sp_field) for issue in issues)
    write_cache_since(output_path, args.since)
    print(f"{len(issues)} tickets written to: {output_path}")


if __name__ == "__main__":
    main()
