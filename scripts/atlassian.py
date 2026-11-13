"""
Shared Atlassian REST helpers for the JIRA and Confluence fetch scripts.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_MAX_RETRIES = 5
_RATE_LIMIT_WAIT = 60  # seconds — fallback when Retry-After header absent
_BACKOFF_BASE = 5  # seconds — base for exponential back-off on 5xx


def require_env(key: str) -> str:
    """require_env returns the environment variable key, or exits with an error when it is unset."""
    value = os.environ.get(key)
    if not value:
        print(f"Error: {key} is required (set it in .env)", file=sys.stderr)
        sys.exit(1)
    return value


def build_auth_header() -> str:
    """build_auth_header returns the Basic auth header built from JIRA_EMAIL and JIRA_TOKEN."""
    raw = f"{require_env('JIRA_EMAIL')}:{require_env('JIRA_TOKEN')}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def get_json(url: str, auth_header: str, params: dict, debug: bool = False) -> dict | list:
    """get_json GETs url with params and returns the parsed JSON body."""
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    if debug:
        print(f"\n  GET {full_url}", file=sys.stderr)
    req = urllib.request.Request(
        full_url,
        headers={"Authorization": auth_header, "Accept": "application/json"},
    )
    return send(req)


def post_json(url: str, auth_header: str, body: dict, debug: bool = False) -> dict:
    """post_json POSTs body as JSON to url and returns the parsed JSON body."""
    if debug:
        print(f"\n  POST {url}  body={json.dumps(body)[:200]}", file=sys.stderr)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    return send(req)


def send(req: urllib.request.Request) -> dict | list:
    """send returns the parsed JSON response, retrying on 429, 5xx and network errors, and raises RuntimeError otherwise."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            body = read_error_body(exc)
            print(f"\n  HTTP {exc.code} from {req.full_url}", file=sys.stderr)
            print(f"  Response: {body[:500]}", file=sys.stderr)

            if exc.code == 401:
                raise RuntimeError("Authentication failed — check JIRA_EMAIL and JIRA_TOKEN") from exc
            if exc.code == 403:
                raise RuntimeError(f"Forbidden — token may lack read permission for {req.full_url}") from exc
            if exc.code == 410:
                raise RuntimeError(
                    f"HTTP 410 Gone — endpoint or resource no longer exists.\n"
                    f"  URL: {req.full_url}\n  Detail: {body[:500]}"
                ) from exc
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After", _RATE_LIMIT_WAIT))
                print(f"  Rate limit hit — waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if attempt == _MAX_RETRIES:
                raise RuntimeError(
                    f"Atlassian API error after {_MAX_RETRIES} retries: HTTP {exc.code}\n"
                    f"  URL: {req.full_url}\n  Detail: {body[:500]}"
                ) from exc
            wait = _BACKOFF_BASE * (2**attempt)
            print(f"  Retrying in {wait}s (attempt {attempt}/{_MAX_RETRIES})...", file=sys.stderr)
            time.sleep(wait)

        except urllib.error.URLError as exc:
            if attempt == _MAX_RETRIES:
                raise RuntimeError(f"Network error after {_MAX_RETRIES} retries: {exc.reason}") from exc
            wait = _BACKOFF_BASE * (2**attempt)
            print(f"\n  Network error ({exc.reason}) — retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)

    return {}  # unreachable; satisfies type checker


def read_error_body(exc: urllib.error.HTTPError) -> str:
    """read_error_body returns the decoded body of exc, or a placeholder when it cannot be read."""
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return "(could not read response body)"


def lookup_account_id(base_url: str, auth_header: str, email: str, debug: bool = False) -> str | None:
    """lookup_account_id returns the Atlassian account ID for email, or None when no user matches."""
    try:
        results = get_json(f"{base_url}/rest/api/3/user/search", auth_header, {"query": email}, debug=debug)
    except Exception:
        return None
    if not isinstance(results, list):
        return None
    for user in results:
        if user.get("emailAddress", "").lower() == email.lower():
            return user.get("accountId")
    return results[0].get("accountId") if results else None
