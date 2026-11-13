#!/usr/bin/env python3
"""
Fetch Confluence pages created and contributed to by a given Atlassian user.

Produces two lists:
  created     — pages where the author is the original creator
  contributed — pages the author edited but did not create

Output: data/{name}_confluence.json, where name is the email before the @

Usage:
    python3 scripts/fetch_confluence.py
    python3 scripts/fetch_confluence.py --email colleague@your-org.com --since 2025-01-01
    python3 scripts/fetch_confluence.py --force

Auth (read from the environment or .env):
    JIRA_URL=https://your-org.atlassian.net
    JIRA_EMAIL=you@your-org.com
    JIRA_TOKEN=<your-api-token>
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from atlassian import build_auth_header, find_user, get_json, require_env
from utils import START_DATE, add_email_arg, load_dotenv, name_from_email, warn_if_stale_cache


_PAGE_LIMIT = 50
_VERSION_WORKERS = 8  # concurrent page version lookups; send() retries on 429


def _extract_date(page: dict) -> str:
    raw = (
        page.get("history", {}).get("createdDate")
        or page.get("version", {}).get("when")
        or ""
    )
    return raw[:10] if raw else ""


def fetch_pages(base_url: str, auth_header: str, cql: str, debug: bool = False) -> list[dict]:
    """fetch_pages returns every page matching cql, without duplicates."""
    url = f"{base_url}/wiki/rest/api/content/search"
    pages: list[dict] = []
    start = 0

    while True:
        params = {
            "cql": cql,
            "limit": _PAGE_LIMIT,
            "start": start,
            "expand": "space,history.createdDate,version",
        }
        data = get_json(url, auth_header, params, debug=debug)
        results = data.get("results", [])

        for r in results:
            web_ui = r.get("_links", {}).get("webui", "")
            version = r.get("version", {})
            pages.append(
                {
                    "id": r.get("id", ""),
                    "title": r.get("title", ""),
                    "space": r.get("space", {}).get("key", ""),
                    "url": f"{base_url}/wiki{web_ui}" if web_ui else "",
                    "created": _extract_date(r),
                    "last_modified": (version.get("when") or "")[:10],
                    "version_number": version.get("number"),
                    # internal field used for post-filtering; stripped before output
                    "_version_author_id": version.get("by", {}).get("accountId", ""),
                }
            )

        fetched = len(results)
        start += fetched

        if fetched < _PAGE_LIMIT or not data.get("_links", {}).get("next"):
            break

    # Deduplicate by page ID (Confluence search can return the same page
    # multiple times across paginated results).
    seen: set[str] = set()
    unique: list[dict] = []
    for p in pages:
        pid = p["id"]
        if pid not in seen:
            seen.add(pid)
            unique.append(p)
    return unique


def find_last_edit(page: dict, base_url: str, auth_header: str, account_id: str, since: str, debug: bool = False) -> str | None:
    """find_last_edit returns the date of the account's latest version of page on or after since, or None when it has none."""
    if page["_version_author_id"] == account_id:
        return page["last_modified"]
    url = f"{base_url}/wiki/api/v2/pages/{page['id']}/versions"
    params = {"limit": _PAGE_LIMIT, "sort": "-modified-date"}
    while url:
        data = get_json(url, auth_header, params, debug=debug)
        for version in data["results"]:
            date = version["createdAt"][:10]
            if date < since:
                return None
            if version["authorId"] == account_id:
                return date
        next_link = data["_links"].get("next")
        url = f"{base_url}{next_link}" if next_link else None
        params = {}
    return None


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    add_email_arg(parser)
    parser.add_argument("--since", default=START_DATE,
                        help=f"Only include pages touched on or after this date (default: {START_DATE})")
    parser.add_argument("--output", default=None, help="Output JSON (default: data/{name}_confluence.json)")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output already exists")
    parser.add_argument("--debug", action="store_true", help="Print request URLs and error bodies")
    args = parser.parse_args()

    output_path = Path(args.output or f"data/{name_from_email(args.email)}_confluence.json")
    cache = json.loads(output_path.read_text()) if output_path.exists() else None

    # NOTE: caches written before edit dates were recorded are fetched again, as if --force was passed.
    if cache and not args.force and all("edited" in p for p in cache["contributed"]):
        print(f"Cache hit: {output_path} already exists. Pass --force to re-fetch.")
        warn_if_stale_cache(output_path, cache.get("since"), args.since)
        sys.exit(0)

    base_url = require_env("JIRA_URL").rstrip("/")
    auth_header = build_auth_header()
    since = args.since
    target_email = args.email

    user = find_user(base_url, auth_header, target_email, debug=args.debug)
    if not user:
        print(f"Error: no Atlassian user found for {target_email}", file=sys.stderr)
        sys.exit(1)
    account_id = user["accountId"]

    print(f"Fetching Confluence pages for: {target_email}  (since {since})")

    print("  Fetching created pages...", end=" ", flush=True)
    created_cql = f'creator = "{account_id}" AND type = page AND created >= "{since}"'
    created = fetch_pages(base_url, auth_header, created_cql, debug=args.debug)
    print(f"{len(created)} found")

    # A page the person edited on or after since was last modified on or after since, so the date filter loses none.
    print("  Fetching contributed pages (edits to others' pages)...", end=" ", flush=True)
    contributed_cql = f'contributor = "{account_id}" AND type = page AND creator != "{account_id}" AND lastmodified >= "{since}"'
    candidates = fetch_pages(base_url, auth_header, contributed_cql, debug=args.debug)
    find_edit = partial(find_last_edit, base_url=base_url, auth_header=auth_header, account_id=account_id, since=since, debug=args.debug)
    with ThreadPoolExecutor(max_workers=_VERSION_WORKERS) as pool:
        edits = list(pool.map(find_edit, candidates))
    contributed = [{**p, "edited": edited} for p, edited in zip(candidates, edits) if edited]
    print(f"{len(contributed)} found")

    # Strip internal field before writing output
    for p in created + contributed:
        p.pop("_version_author_id", None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(
        {"email": target_email, "since": since, "created": created, "contributed": contributed},
        indent=2,
    ))
    print(f"Confluence data written to: {output_path}")


if __name__ == "__main__":
    main()
