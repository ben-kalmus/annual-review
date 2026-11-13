#!/usr/bin/env python3
"""
Fetch a person's resolved JIRA tickets from the JIRA REST API into a JSON file.

Selects tickets with status Done, resolved on or after --since, where the person
is the assignee or the reporter, excluding access-request issue types.

Output: data/{name}_jira.json, where name is the email before the @
  {
    "email": "...", "display_name": "...", "account_id": "...", "since": "YYYY-MM-DD",
    "tickets": [{"Issue key": "...", "Assignee ID": "...", "Sprints": [...], ...}]
  }

Usage:
    python3 scripts/fetch_jira.py
    python3 scripts/fetch_jira.py --email colleague@your-org.com --since 2026-01-01 --force

Auth (read from the environment or .env):
    JIRA_URL=https://your-org.atlassian.net
    JIRA_EMAIL=you@your-org.com
    JIRA_TOKEN=<your-api-token>
"""

import argparse
import json
import sys
from pathlib import Path

from atlassian import build_auth_header, find_user, get_json, require_env, search_issues
from utils import START_DATE, add_email_arg, load_dotenv, name_from_email, warn_if_stale_cache

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


def to_ticket(issue: dict, sprint_field: str | None, sp_field: str | None) -> dict:
    """to_ticket returns the ticket record for issue, with every label and every sprint."""
    f = issue["fields"]
    return {
        "Summary": nested(f, "summary"),
        "Issue key": issue["key"],
        "Issue Type": nested(f, "issuetype", "name"),
        "Status": nested(f, "status", "name"),
        "Status Category": nested(f, "status", "statusCategory", "name"),
        "Project key": nested(f, "project", "key"),
        "Priority": nested(f, "priority", "name"),
        "Assignee": nested(f, "assignee", "displayName"),
        "Assignee ID": nested(f, "assignee", "accountId"),
        "Reporter": nested(f, "reporter", "displayName"),
        "Reporter ID": nested(f, "reporter", "accountId"),
        "Created": nested(f, "created"),
        "Resolved": nested(f, "resolutiondate"),
        "Labels": f.get("labels") or [],
        "Sprints": [s["name"] for s in f.get(sprint_field) or []],
        "Story Points": f.get(sp_field),
        "Parent key": nested(f, "parent", "key"),
        "Parent summary": nested(f, "parent", "fields", "summary"),
        "Description": nested(f, "description"),
    }


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    add_email_arg(parser)
    parser.add_argument("--since", default=START_DATE, help=f"Earliest resolved date YYYY-MM-DD (default: {START_DATE})")
    parser.add_argument("--output", default=None, help="Output JSON (default: data/{name}_jira.json)")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output already exists")
    parser.add_argument("--debug", action="store_true", help="Print request URLs and error bodies")
    args = parser.parse_args()

    output_path = Path(args.output or f"data/{name_from_email(args.email)}_jira.json")

    if output_path.exists() and not args.force:
        print(f"Cache hit: {output_path} already exists. Pass --force to re-fetch.")
        warn_if_stale_cache(output_path, json.loads(output_path.read_text()).get("since"), args.since)
        sys.exit(0)

    base_url = require_env("JIRA_URL").rstrip("/")
    auth_header = build_auth_header()

    user = find_user(base_url, auth_header, args.email, debug=args.debug)
    if not user:
        print(f"Error: no JIRA user found for {args.email}", file=sys.stderr)
        sys.exit(1)
    account_id = user["accountId"]

    sprint_field, sp_field = find_field_ids(base_url, auth_header, debug=args.debug)
    jql = (
        f'(assignee = "{account_id}" OR reporter = "{account_id}") AND status = Done'
        f' AND resolutiondate >= "{args.since}"'
        ' AND issuetype NOT IN ("Admin Access", "Access Request")'
        " ORDER BY resolutiondate ASC"
    )
    fields = BASE_FIELDS + [f for f in (sprint_field, sp_field) if f]

    print(f"Fetching JIRA tickets for: {user['displayName']} ({args.email})  (since {args.since})")
    issues = search_issues(base_url, auth_header, jql, fields, debug=args.debug)

    output = {
        "email": args.email,
        "display_name": user["displayName"],
        "account_id": account_id,
        "since": args.since,
        "tickets": [to_ticket(issue, sprint_field, sp_field) for issue in issues],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    print(f"{len(issues)} tickets written to: {output_path}")


if __name__ == "__main__":
    main()
