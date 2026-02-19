#!/usr/bin/env python3
"""
Fetch total team ticket counts and story points per sprint from the JIRA REST API.

Reads the author's stripped JIRA CSV to discover which sprints they worked in,
then queries JIRA for the full team's resolved tickets in each of those sprints.
Output is cached to avoid hitting the API on every analysis run.

Output: data/{author}_sprint_totals.json
  {
    "Composition #41": {"total_tickets": 25, "total_story_points": 80.0},
    ...
  }

Usage:
    python3 scripts/fetch_sprint_totals.py --author ben-kalmus
    python3 scripts/fetch_sprint_totals.py --author ben-kalmus --force
    python3 scripts/fetch_sprint_totals.py --author ben-kalmus --sp-field customfield_10028

Auth (all three required — flag overrides env var):
    export JIRA_URL=https://algolia.atlassian.net
    export JIRA_EMAIL=you@algolia.com
    export JIRA_TOKEN=<your-api-token>
"""

import argparse
import base64
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path


def load_dotenv(dotenv_path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (no-op if file absent)."""
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
        if key and key not in os.environ:  # shell env takes precedence
            os.environ[key] = val


# ── constants ─────────────────────────────────────────────────────────────────

_MAX_RETRIES        = 5
_RATE_LIMIT_WAIT    = 60   # seconds — fallback when Retry-After header absent
_BACKOFF_BASE       = 5    # seconds — base for exponential back-off on 5xx
_DEFAULT_SP_FIELD   = "customfield_10016"
_SP_FIELD_NAMES     = {"story points", "story point estimate", "story points estimate"}


# ── helpers ───────────────────────────────────────────────────────────────────

def build_auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    """Safely read and decode the response body from an HTTPError."""
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return "(could not read response body)"


def jira_get(url: str, auth_header: str, params: dict, debug: bool = False) -> dict | list:
    """
    GET a JIRA REST endpoint and return parsed JSON.
    Retries on HTTP 429 (rate limit) and 5xx errors with back-off.
    Raises RuntimeError on auth failures or exhausted retries.
    """
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
                raise RuntimeError(
                    "Authentication failed — check JIRA_EMAIL and JIRA_TOKEN"
                ) from exc
            if exc.code == 403:
                raise RuntimeError(
                    "Forbidden — token may lack read permissions on this project"
                ) from exc
            if exc.code == 410:
                raise RuntimeError(
                    f"HTTP 410 Gone — endpoint or resource no longer exists.\n"
                    f"  URL: {full_url}\n"
                    f"  Detail: {body[:500]}"
                ) from exc
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After", _RATE_LIMIT_WAIT))
                print(f"  Rate limit hit — waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                wait = _BACKOFF_BASE * (2 ** attempt)
                print(
                    f"  Retrying in {wait}s (attempt {attempt}/{_MAX_RETRIES})...",
                    file=sys.stderr,
                )
                if attempt == _MAX_RETRIES:
                    raise RuntimeError(
                        f"JIRA API error after {_MAX_RETRIES} retries: HTTP {exc.code}\n"
                        f"  URL: {full_url}\n"
                        f"  Detail: {body[:500]}"
                    ) from exc
                time.sleep(wait)

        except urllib.error.URLError as exc:
            wait = _BACKOFF_BASE * (2 ** attempt)
            print(f"\n  Network error ({exc.reason}) — retrying in {wait}s...", file=sys.stderr)
            if attempt == _MAX_RETRIES:
                raise RuntimeError(f"Network error after {_MAX_RETRIES} retries: {exc.reason}") from exc
            time.sleep(wait)

    return {}  # unreachable; satisfies type checker


def jira_post(url: str, auth_header: str, body: dict, debug: bool = False) -> dict | list:
    """
    POST a JIRA REST endpoint with a JSON body and return parsed JSON.
    Same retry/error-handling behaviour as jira_get.
    """
    payload = json.dumps(body).encode("utf-8")
    if debug:
        print(f"\n  POST {url}  body={json.dumps(body)[:200]}", file=sys.stderr)
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            body_str = _read_error_body(exc)
            print(f"\n  HTTP {exc.code} from {url}", file=sys.stderr)
            print(f"  Response: {body_str[:500]}", file=sys.stderr)

            if exc.code == 401:
                raise RuntimeError("Authentication failed — check JIRA_EMAIL and JIRA_TOKEN") from exc
            if exc.code == 403:
                raise RuntimeError("Forbidden — token may lack read permissions on this project") from exc
            if exc.code == 410:
                raise RuntimeError(
                    f"HTTP 410 Gone — endpoint or resource no longer exists.\n"
                    f"  URL: {url}\n"
                    f"  Detail: {body_str[:500]}"
                ) from exc
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After", _RATE_LIMIT_WAIT))
                print(f"  Rate limit hit — waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                wait = _BACKOFF_BASE * (2 ** attempt)
                print(f"  Retrying in {wait}s (attempt {attempt}/{_MAX_RETRIES})...", file=sys.stderr)
                if attempt == _MAX_RETRIES:
                    raise RuntimeError(
                        f"JIRA API error after {_MAX_RETRIES} retries: HTTP {exc.code}\n"
                        f"  URL: {url}\n"
                        f"  Detail: {body_str[:500]}"
                    ) from exc
                time.sleep(wait)

        except urllib.error.URLError as exc:
            wait = _BACKOFF_BASE * (2 ** attempt)
            print(f"\n  Network error ({exc.reason}) — retrying in {wait}s...", file=sys.stderr)
            if attempt == _MAX_RETRIES:
                raise RuntimeError(f"Network error after {_MAX_RETRIES} retries: {exc.reason}") from exc
            time.sleep(wait)

    return {}


# ── CSV helpers ───────────────────────────────────────────────────────────────

def infer_project(csv_path: Path) -> str:
    """Return the most common Project key in the CSV."""
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    counts = Counter(r.get("Project key", "").strip() for r in rows if r.get("Project key", "").strip())
    if not counts:
        print(f"Error: no 'Project key' values found in {csv_path}", file=sys.stderr)
        sys.exit(1)
    return counts.most_common(1)[0][0]


def sprints_from_csv(csv_path: Path, project: str) -> list[str]:
    """Return sorted unique sprint names from rows belonging to `project`."""
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    sprints: set[str] = set()
    for r in rows:
        if r.get("Project key", "").strip() != project:
            continue
        for col in ("Sprint", "Sprint_2", "Sprint_3"):
            val = r.get(col, "").strip()
            if val:
                sprints.add(val)
    return sorted(sprints)


# ── story-point field discovery ───────────────────────────────────────────────

def discover_sp_field(base_url: str, auth_header: str, debug: bool = False) -> str | None:
    """
    Query /rest/api/3/field and find the story-points custom field ID.
    Returns None if not found.
    """
    try:
        fields = jira_get(f"{base_url}/rest/api/3/field", auth_header, {}, debug=debug)
        if isinstance(fields, list):
            for field in fields:
                if field.get("name", "").lower() in _SP_FIELD_NAMES:
                    return field["id"]
    except Exception as exc:
        print(f"  Warning: field discovery failed — {exc}", file=sys.stderr)
    return None


# ── sprint fetch ──────────────────────────────────────────────────────────────

def fetch_sprint_total(
    base_url: str,
    auth_header: str,
    project: str,
    sprint_name: str,
    sp_field: str,
    debug: bool = False,
) -> dict:
    """
    Query JIRA for all Done tickets in `project` during `sprint_name`.
    Uses POST /rest/api/2/search to avoid JQL URL-encoding issues.
    Paginates automatically. Returns {"total_tickets": N, "total_story_points": F}.
    """
    jql = f'project="{project}" AND sprint="{sprint_name}" AND status=Done'
    total_tickets = 0
    total_sp = 0.0
    null_sp_count = 0
    next_page_token: str | None = None

    while True:
        # /rest/api/3/search/jql uses cursor-based pagination via nextPageToken
        # and "limit" instead of "maxResults"
        body: dict = {"jql": jql, "fields": [sp_field], "maxResults": 100}
        if next_page_token:
            body["nextPageToken"] = next_page_token

        data = jira_post(
            f"{base_url}/rest/api/3/search/jql",
            auth_header,
            body,
            debug=debug,
        )
        issues = data.get("issues", [])

        for issue in issues:
            sp = issue.get("fields", {}).get(sp_field)
            if sp is not None:
                total_sp += float(sp)
            else:
                null_sp_count += 1

        total_tickets += len(issues)
        next_page_token = data.get("nextPageToken")

        if not issues or not next_page_token:
            break

    return {
        "total_tickets": total_tickets,
        "total_story_points": round(total_sp, 1),
        "_null_sp_count": null_sp_count,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def resolve(flag_val: str | None, env_key: str, label: str) -> str:
    """Return flag value if set, else env var, else exit with a clear message."""
    value = flag_val or __import__("os").environ.get(env_key)
    if not value:
        print(f"Error: --{label.lower().replace(' ', '-')} / {env_key} is required", file=sys.stderr)
        sys.exit(1)
    return value


def main():
    # Load .env from repo root before anything else so env vars are available
    _repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(_repo_root / ".env")

    parser = argparse.ArgumentParser()
    parser.add_argument("--author",   required=True, help="GitHub login; drives default file paths")
    parser.add_argument("--jira-url", default=None,  help="JIRA base URL (env: JIRA_URL)")
    parser.add_argument("--email",    default=None,  help="Atlassian account email (env: JIRA_EMAIL)")
    parser.add_argument("--token",    default=None,  help="JIRA API token (env: JIRA_TOKEN)")
    parser.add_argument("--project",  default=None,  help="Project key (default: inferred from CSV)")
    _sp_field_default = os.environ.get("JIRA_SP_FIELD", _DEFAULT_SP_FIELD)
    parser.add_argument("--sp-field", default=_sp_field_default, help=f"Story points custom field ID (env: JIRA_SP_FIELD, default: {_DEFAULT_SP_FIELD})")
    parser.add_argument("--input",    default=None,  help="Stripped JIRA CSV (default: data/{author}_jira.csv)")
    parser.add_argument("--output",   default=None,  help="Output JSON (default: data/{author}_sprint_totals.json)")
    parser.add_argument("--force",    action="store_true", help="Re-fetch even if output already exists")
    parser.add_argument("--debug",    action="store_true", help="Print each request URL and response body on errors")
    args = parser.parse_args()

    author = args.author
    input_path  = Path(args.input  or f"data/{author}_jira.csv")
    output_path = Path(args.output or f"data/{author}_sprint_totals.json")

    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Cache check
    if output_path.exists() and not args.force:
        print(f"Cache hit: {output_path} already exists. Pass --force to re-fetch.")
        sys.exit(0)

    # Credential resolution
    base_url = resolve(args.jira_url, "JIRA_URL",   "jira-url").rstrip("/")
    email    = resolve(args.email,    "JIRA_EMAIL",  "email")
    token    = resolve(args.token,    "JIRA_TOKEN",  "token")
    auth_header = build_auth_header(email, token)

    # Project and sprints
    project = args.project or infer_project(input_path)
    sprints = sprints_from_csv(input_path, project)

    if not sprints:
        print(f"No sprints found for project '{project}' in {input_path}. Nothing to fetch.")
        sys.exit(0)

    print(f"Project: {project}  |  {len(sprints)} sprints to fetch")
    print(f"SP field: {args.sp_field}")

    # Lazy SP field discovery — check after first sprint if all SP values are null
    sp_field = args.sp_field
    discovered = False

    results: dict[str, dict] = {}
    total_null_sp = 0

    for i, sprint in enumerate(sprints, 1):
        print(f"\r  [{i}/{len(sprints)}] {sprint:<40}", end="", flush=True)
        result = fetch_sprint_total(base_url, auth_header, project, sprint, sp_field, debug=args.debug)

        # After first sprint, trigger lazy discovery if all SP values were null
        if i == 1 and not discovered and result["total_tickets"] > 0 and result["_null_sp_count"] == result["total_tickets"]:
            print(f"\n  SP field '{sp_field}' returned no values — attempting auto-discovery...", file=sys.stderr)
            found = discover_sp_field(base_url, auth_header, debug=args.debug)
            if found and found != sp_field:
                print(f"  Discovered SP field: {found}  (pass --sp-field {found} to skip discovery next time)", file=sys.stderr)
                sp_field = found
                discovered = True
                # Re-fetch the first sprint with the correct field
                result = fetch_sprint_total(base_url, auth_header, project, sprint, sp_field, debug=args.debug)

        total_null_sp += result.pop("_null_sp_count")
        results[sprint] = result

    print()  # newline after progress

    if total_null_sp > 0:
        print(
            f"  Note: {total_null_sp} team tickets had no story points in field '{sp_field}'. "
            f"If totals seem low, try --sp-field with a different field ID.",
            file=sys.stderr,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))
    print(f"Sprint totals written to: {output_path}")


if __name__ == "__main__":
    main()
