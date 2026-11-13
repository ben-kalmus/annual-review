#!/usr/bin/env bash
# scripts/collect_author.sh
#
# Fetch and analyse GitHub PR, JIRA, and Confluence data for one person.
#
# Usage:
#   ./scripts/collect_author.sh --git
#   ./scripts/collect_author.sh --git --jira --confluence --export-md
#   ./scripts/collect_author.sh --author <github-login> --email <atlassian-email> --org my-company --git --jira --confluence --export-md
#   ./scripts/collect_author.sh --jira   # JIRA only, no GitHub fetch
#
# --author                GitHub login (default: the login gh is authenticated as).
#                         Names the GitHub files: data/<author>_*.
# --email                 Atlassian email of the person (default: JIRA_EMAIL in .env).
#                         Names the JIRA and Confluence files: data/<name>_*, where
#                         <name> is the email before the @.
# --git                   Fetch GitHub PRs (authored + reviewed).
#                         Output: data/<author>_prs.json, data/<author>_reviewed_prs.json
# --org                   GitHub org to limit PR discovery to (e.g. my-company).
#                         Omit to include all orgs the user has activity in.
# --jira                  Fetch resolved JIRA tickets and sprint totals from the JIRA API.
#                         Output: data/<name>_jira.json, data/<name>_sprint_totals.json
# --confluence            Fetch Confluence contributions (requires .env creds).
#                         Output: data/<name>_confluence.json
# --export-md             Generate data/<author>_review.md after all steps succeed.
# --since                 Start date, YYYY-MM-DD (default: START_DATE in scripts/utils.py).
# --force                 Re-fetch all data even if output files already exist.

set -euo pipefail

# Ctrl+C only kills the foreground shell, not the fetch_prs.py /
# fetch_reviewed_prs.py children backgrounded below — kill them explicitly
# so a cancelled run doesn't leave orphaned fetches still hitting the API.
trap 'jobs -p | xargs -r kill 2>/dev/null' INT TERM EXIT

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts"

# Load .env from repo root if present (shell env takes precedence)
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
    set +a
fi

AUTHOR=""
EMAIL="${JIRA_EMAIL:-}"
SINCE=""
ORG=""
RUN_GIT=false
RUN_JIRA=false
RUN_CONFLUENCE=false
EXPORT_MD=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --author)            AUTHOR="$2";              shift 2 ;;
        --email)             EMAIL="$2";               shift 2 ;;
        --git)               RUN_GIT=true;             shift ;;
        --jira)              RUN_JIRA=true;            shift ;;
        --confluence)        RUN_CONFLUENCE=true;      shift ;;
        --export-md)         EXPORT_MD=true;           shift ;;
        --force)             FORCE=true;               shift ;;
        --since)             SINCE="$2";               shift 2 ;;
        --org)               ORG="$2";                 shift 2 ;;
        *)                   echo "Unknown argument: $1"; exit 1 ;;
    esac
done

[[ -z "$AUTHOR" ]] && AUTHOR="$(gh api user --jq .login)"
if [[ -z "$EMAIL" && ( "$RUN_JIRA" == true || "$RUN_CONFLUENCE" == true || "$EXPORT_MD" == true ) ]]; then
    echo "Error: --email or JIRA_EMAIL in .env is required for --jira, --confluence and --export-md"
    exit 1
fi
NAME="${EMAIL%%@*}"

SINCE_ARGS=()
[[ -n "$SINCE" ]] && SINCE_ARGS=(--since "$SINCE")

ORG_ARGS=()
[[ -n "$ORG" ]] && ORG_ARGS=(--org "$ORG")

FORCE_ARG=()
[[ "$FORCE" == true ]] && FORCE_ARG=(--force)

CONFLUENCE_OK=false

echo "════════════════════════════════════════════════"
echo "  Collecting data for: $AUTHOR ${EMAIL:+($EMAIL)}"
echo "════════════════════════════════════════════════"

# ── Fetch ─────────────────────────────────────────

if [[ "$RUN_GIT" == true ]]; then
    echo ""
    echo "── Fetch: PRs (parallel) ────────────────────────"
    python3 "$SCRIPTS/fetch_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" "${ORG_ARGS[@]}" "${FORCE_ARG[@]}" &
    PID_AUTHORED=$!
    python3 "$SCRIPTS/fetch_reviewed_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" "${ORG_ARGS[@]}" "${FORCE_ARG[@]}" &
    PID_REVIEWED=$!

    wait $PID_AUTHORED || { echo "Error: fetch_prs.py failed"; exit 1; }
    wait $PID_REVIEWED || { echo "Error: fetch_reviewed_prs.py failed"; exit 1; }
fi

if [[ "$RUN_JIRA" == true ]]; then
    echo ""
    echo "── Fetch: JIRA ──────────────────────────────────"
    python3 "$SCRIPTS/fetch_jira.py" --email "$EMAIL" "${SINCE_ARGS[@]}" "${FORCE_ARG[@]}" \
        || { echo "Error: fetch_jira.py failed (check JIRA credentials in .env)"; exit 1; }

    echo ""
    echo "── Fetch: Sprint Totals ─────────────────────────"
    python3 "$SCRIPTS/fetch_sprint_totals.py" --email "$EMAIL" "${FORCE_ARG[@]}" \
        || echo "  Sprint totals unavailable — continuing without (check JIRA credentials in .env)."
fi

if [[ "$RUN_CONFLUENCE" == true ]]; then
    echo ""
    echo "── Fetch: Confluence ────────────────────────────"
    if python3 "$SCRIPTS/fetch_confluence.py" --email "$EMAIL" "${SINCE_ARGS[@]}" "${FORCE_ARG[@]}"; then
        CONFLUENCE_OK=true
    else
        echo "  Confluence fetch failed — skipping analysis (check JIRA credentials in .env)."
    fi
fi

# ── Analyse ───────────────────────────────────────

if [[ "$RUN_GIT" == true ]]; then
    echo ""
    echo "── Analyse: PRs ─────────────────────────────────"
    python3 "$SCRIPTS/analyse_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}"
fi

if [[ "$RUN_JIRA" == true ]]; then
    echo ""
    echo "── Analyse: JIRA ────────────────────────────────"
    python3 "$SCRIPTS/analyse_jira.py" --email "$EMAIL" "${SINCE_ARGS[@]}"
fi

if [[ "$CONFLUENCE_OK" == true ]]; then
    echo ""
    echo "── Analyse: Confluence ──────────────────────────"
    python3 "$SCRIPTS/analyse_confluence.py" --email "$EMAIL" "${SINCE_ARGS[@]}"
fi

# ── Export ────────────────────────────────────────

if [[ "$EXPORT_MD" == true ]]; then
    echo ""
    echo "── Export: Markdown ─────────────────────────────"
    python3 "$SCRIPTS/export_markdown.py" --author "$AUTHOR" --email "$EMAIL" "${SINCE_ARGS[@]}"
fi

echo ""
echo "════════════════════════════════════════════════"
echo "  Done. Files written to $REPO_ROOT/data/"
if [[ "$RUN_GIT" == true ]]; then
    echo "    ${AUTHOR}_prs.json"
    echo "    ${AUTHOR}_reviewed_prs.json"
fi
if [[ "$RUN_JIRA" == true ]]; then
    echo "    ${NAME}_jira.json"
    [[ -f "data/${NAME}_sprint_totals.json" ]] && echo "    ${NAME}_sprint_totals.json"
fi
[[ -f "data/${NAME}_confluence.json" ]] && echo "    ${NAME}_confluence.json"
if [[ "$EXPORT_MD" == true ]]; then
    echo "    ${AUTHOR}_review.md"
fi
echo "════════════════════════════════════════════════"
