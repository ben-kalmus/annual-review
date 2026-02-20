#!/usr/bin/env python3
"""
Fetch Confluence pages created and contributed to by a given Atlassian user.

Produces two lists:
  created     — pages where the author is the original creator
  contributed — pages the author edited but did not create

Output: data/{author}_confluence.json

Usage:
    python3 scripts/fetch_confluence.py --author ben-kalmus
    python3 scripts/fetch_confluence.py --author ben-kalmus --since 2025-01-01
    python3 scripts/fetch_confluence.py --author ben-kalmus --force

Auth (all three required — flag overrides env var):
    export JIRA_URL=https://algolia.atlassian.net
    export JIRA_EMAIL=you@algolia.com
    export JIRA_TOKEN=<your-api-token>
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


_DEFAULT_SINCE = "2025-05-28"
_MAX_RETRIES = 5
_RATE_LIMIT_WAIT = 60
_BACKOFF_BASE = 5
_PAGE_LIMIT = 50


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def build_auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return "(could not read response body)"


def confluence_get(url: str, auth_header: str, params: dict, debug: bool = False) -> dict:
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    if debug:
        print(f"\n  GET {full_url}", file=sys.stderr)
    req = urllib.request.Request(
        full_url,
        headers={"Authorization": auth_header, "Accept": "application/json"},
    )

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            body = _read_error_body(exc)
            print(f"\n  HTTP {exc.code} from {url}", file=sys.stderr)
            print(f"  Response: {body[:500]}", file=sys.stderr)

            if exc.code == 401:
                raise RuntimeError("Authentication failed — check JIRA_EMAIL and JIRA_TOKEN") from exc
            if exc.code == 403:
                raise RuntimeError("Forbidden — token may lack read permissions on Confluence") from exc
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After", _RATE_LIMIT_WAIT))
                print(f"  Rate limit hit — waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                wait = _BACKOFF_BASE * (2 ** attempt)
                print(f"  Retrying in {wait}s (attempt {attempt}/{_MAX_RETRIES})...", file=sys.stderr)
                if attempt == _MAX_RETRIES:
                    raise RuntimeError(
                        f"Confluence API error after {_MAX_RETRIES} retries: HTTP {exc.code}\n"
                        f"  URL: {full_url}\n  Detail: {body[:500]}"
                    ) from exc
                time.sleep(wait)

        except urllib.error.URLError as exc:
            wait = _BACKOFF_BASE * (2 ** attempt)
            print(f"\n  Network error ({exc.reason}) — retrying in {wait}s...", file=sys.stderr)
            if attempt == _MAX_RETRIES:
                raise RuntimeError(f"Network error after {_MAX_RETRIES} retries: {exc.reason}") from exc
            time.sleep(wait)

    return {}


def _extract_date(page: dict) -> str:
    raw = (
        page.get("history", {}).get("createdDate")
        or page.get("version", {}).get("when")
        or ""
    )
    return raw[:10] if raw else ""


def fetch_pages(base_url: str, auth_header: str, cql: str, debug: bool = False) -> list[dict]:
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
        data = confluence_get(url, auth_header, params, debug=debug)
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
                }
            )

        fetched = len(results)
        start += fetched

        if fetched < _PAGE_LIMIT:
            break

    return pages


def resolve(flag_val: str | None, env_key: str, label: str) -> str:
    value = flag_val or os.environ.get(env_key)
    if not value:
        print(f"Error: --{label.lower().replace(' ', '-')} / {env_key} is required", file=sys.stderr)
        sys.exit(1)
    return value


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
        sys.exit(0)

    base_url = resolve(args.jira_url, "JIRA_URL", "jira-url").rstrip("/")
    email = resolve(args.email, "JIRA_EMAIL", "email")
    token = resolve(args.token, "JIRA_TOKEN", "token")
    auth_header = build_auth_header(email, token)
    since = args.since

    target_email = args.confluence_email or email
    user_cql = f'"{target_email}"'

    print(f"Fetching Confluence pages for: {target_email}  (since {since})")

    print("  Fetching created pages...", end=" ", flush=True)
    created_cql = f'creator = {user_cql} AND type = page AND created >= "{since}"'
    created = fetch_pages(base_url, auth_header, created_cql, debug=args.debug)
    print(f"{len(created)} found")

    print("  Fetching contributed pages (edits to others' pages)...", end=" ", flush=True)
    contributed_cql = (
        f'contributor = {user_cql} AND type = page '
        f'AND creator != {user_cql} AND lastModified >= "{since}"'
    )
    contributed = fetch_pages(base_url, auth_header, contributed_cql, debug=args.debug)
    print(f"{len(contributed)} found")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(
        {"email": email, "since": since, "created": created, "contributed": contributed},
        indent=2,
    ))
    print(f"Confluence data written to: {output_path}")


if __name__ == "__main__":
    main()
