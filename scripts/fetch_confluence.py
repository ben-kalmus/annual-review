#!/usr/bin/env python3
"""
Fetch Confluence pages created and contributed to by a given Atlassian user.

Produces two lists:
  created     — pages where the author is the original creator
  contributed — pages the author edited but did not create

Output: data/{author}_confluence.json

Usage:
    python3 scripts/fetch_confluence.py --author <your-login>
    python3 scripts/fetch_confluence.py --author <your-login> --since 2025-01-01
    python3 scripts/fetch_confluence.py --author <your-login> --force

Auth (all three required — flag overrides env var):
    export JIRA_URL=https://your-org.atlassian.net
    export JIRA_EMAIL=you@your-org.com
    export JIRA_TOKEN=<your-api-token>
"""

import argparse
import json
import sys
from pathlib import Path

from atlassian import build_auth_header, get_json, load_dotenv, lookup_account_id, resolve
from utils import warn_if_stale_cache


_DEFAULT_SINCE = "2025-05-28"
_PAGE_LIMIT = 50


def _extract_date(page: dict) -> str:
    raw = (
        page.get("history", {}).get("createdDate")
        or page.get("version", {}).get("when")
        or ""
    )
    return raw[:10] if raw else ""


def get_current_user_account_id(base_url: str, auth_header: str, debug: bool = False) -> str | None:
    """Return the account ID of the authenticated user via the Confluence API."""
    try:
        result = get_json(
            f"{base_url}/wiki/rest/api/user/current",
            auth_header,
            {},
            debug=debug,
        )
        return result.get("accountId")
    except Exception:
        return None


def fetch_pages(
    base_url: str,
    auth_header: str,
    cql: str,
    stop_before: str | None = None,
    max_results: int | None = None,
    debug: bool = False,
) -> list[dict]:
    """Fetch pages matching a CQL query.

    stop_before: if set (YYYY-MM-DD), stop paginating once all results in a batch
    are older than this date. Use with ORDER BY lastModified DESC queries to avoid
    paginating through the full history.
    max_results: hard cap on total pages fetched (safety net for large result sets).
    """
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

        if max_results and len(pages) >= max_results:
            break
        # Early exit: results are ordered DESC by lastModified, so once the oldest
        # result in this batch predates our cutoff, all subsequent pages will too.
        if stop_before and results:
            oldest_in_batch = (
                results[-1].get("version", {}).get("when") or ""
            )[:10]
            if oldest_in_batch and oldest_in_batch < stop_before:
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


def main():
    _repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(_repo_root / ".env")

    parser = argparse.ArgumentParser()
    parser.add_argument("--author", required=True, help="GitHub login; drives default output path")
    parser.add_argument("--jira-url", default=None, help="Atlassian base URL (env: JIRA_URL)")
    parser.add_argument("--email", default=None, help="Your Atlassian account email for auth (env: JIRA_EMAIL)")
    parser.add_argument("--token", default=None, help="Your API token (env: JIRA_TOKEN)")
    parser.add_argument("--confluence-email", default=None,
                        help="Atlassian email of the person to fetch pages for "
                             "(default: same as --email). Use this to fetch a "
                             "colleague's pages with your own token.")
    parser.add_argument("--since", default=_DEFAULT_SINCE,
                        help=f"Only include pages touched on or after this date (default: {_DEFAULT_SINCE})")
    parser.add_argument("--output", default=None, help="Output JSON (default: data/{author}_confluence.json)")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output already exists")
    parser.add_argument("--debug", action="store_true", help="Print request URLs and error bodies")
    args = parser.parse_args()

    author = args.author
    output_path = Path(args.output or f"data/{author}_confluence.json")

    if output_path.exists() and not args.force:
        print(f"Cache hit: {output_path} already exists. Pass --force to re-fetch.")
        warn_if_stale_cache(output_path, json.loads(output_path.read_text()).get("since"), args.since)
        sys.exit(0)

    base_url = resolve(args.jira_url, "JIRA_URL", "jira-url").rstrip("/")
    email = resolve(args.email, "JIRA_EMAIL", "email")
    token = resolve(args.token, "JIRA_TOKEN", "token")
    auth_header = build_auth_header(email, token)
    since = args.since

    account_id: str | None = None
    colleague_email = args.confluence_email
    if colleague_email and colleague_email != email:
        # Querying for a colleague — resolve their account ID for CQL
        print(f"Looking up account ID for: {colleague_email}...", end=" ", flush=True)
        account_id = lookup_account_id(base_url, auth_header, colleague_email, debug=args.debug)
        if account_id:
            user_cql = f'"{account_id}"'
            print(f"found ({account_id})")
        else:
            user_cql = f'"{colleague_email}"'
            print("not found — falling back to email in CQL")
        target_email = colleague_email
    else:
        # Querying for yourself — currentUser() is reliable and avoids account ID lookup
        user_cql = "currentUser()"
        target_email = email
        account_id = get_current_user_account_id(base_url, auth_header, debug=args.debug)

    print(f"Fetching Confluence pages for: {target_email}  (since {since})")

    print("  Fetching created pages...", end=" ", flush=True)
    created_cql = f'creator = {user_cql} AND type = page AND created >= "{since}"'
    created = fetch_pages(base_url, auth_header, created_cql, debug=args.debug)
    print(f"{len(created)} found")

    # Fetch pages the user contributed to but did not create.
    # ORDER BY lastModified DESC + stop_before lets us bail out as soon as we
    # reach pages that predate the review window, avoiding pagination through
    # thousands of old edits. We then post-filter to pages where the user was
    # the last editor (version.by.accountId == account_id) — the only reliable
    # per-contribution signal available without fetching per-page version history.
    print("  Fetching contributed pages (edits to others' pages)...", end=" ", flush=True)
    # No lastModified date filter in CQL — stop_before handles the cutoff by
    # breaking pagination once a batch goes older than `since`. Adding the date
    # filter here would make stop_before unreachable (all results would already
    # satisfy it) and we'd paginate the full history.
    contributed_cql = (
        f'contributor = {user_cql} AND type = page '
        f'AND creator != {user_cql} '
        f'ORDER BY lastModified DESC'
    )
    # Cap at 1 000 scanned pages — enough for any realistic contributor.
    # stop_before provides an earlier exit for typical cases; max_results is a
    # safety net for highly active contributors whose recent-page count is large.
    contributed = fetch_pages(
        base_url, auth_header, contributed_cql,
        stop_before=since, max_results=1000, debug=args.debug,
    )
    if account_id:
        contributed = [p for p in contributed if p.get("_version_author_id") == account_id]
    print(f"{len(contributed)} found")

    # Strip internal field before writing output
    for p in created + contributed:
        p.pop("_version_author_id", None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(
        {"email": email, "since": since, "created": created, "contributed": contributed},
        indent=2,
    ))
    print(f"Confluence data written to: {output_path}")


if __name__ == "__main__":
    main()
