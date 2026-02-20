#!/usr/bin/env bash
# scripts/collect_author.sh
#
# Fetch and analyse all PR (and optionally JIRA/Confluence) data for a given
# GitHub author in one shot.
#
# Usage:
#   ./scripts/collect_author.sh <github-login>
#   ./scripts/collect_author.sh <github-login> --since 2025-01-01
#   ./scripts/collect_author.sh <github-login> --jira
#   ./scripts/collect_author.sh <github-login> --confluence
#   ./scripts/collect_author.sh <github-login> --org my-company --jira --confluence --export-md
#   ./scripts/collect_author.sh <github-login> --force
#
# --org                   GitHub org to limit PR discovery to (e.g. my-company).
#                         Omit to include all orgs the user has activity in.
# --jira                  Strip JIRA.csv (from repo root) and analyse it.
#                         Input:  JIRA.csv  (must exist in repo root)
#                         Output: data/<author>_jira.csv
# --confluence            Fetch and analyse Confluence contributions (requires .env creds).
#                         Output: data/<author>_confluence.json
# --confluence-email      Atlassian email of the person to fetch Confluence pages for.
#                         Defaults to JIRA_EMAIL in .env (i.e. yourself).
#                         Use this to fetch a colleague's pages with your own token.
# --export-md             Generate data/<author>_review.md after all steps succeed.
# --force                 Re-fetch all data even if output files already exist.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts"

# Load .env from repo root if present (shell env takes precedence)
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
    set +a
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <github-login> [--since YYYY-MM-DD] [--jira] [--confluence] [--export-md] [--force]"
    exit 1
fi

AUTHOR="$1"
shift

SINCE=""
ORG=""
RUN_JIRA=false
RUN_CONFLUENCE=false
CONFLUENCE_EMAIL=""
EXPORT_MD=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jira)              RUN_JIRA=true;            shift ;;
        --confluence)        RUN_CONFLUENCE=true;      shift ;;
        --confluence-email)  CONFLUENCE_EMAIL="$2";    shift 2 ;;
        --export-md)         EXPORT_MD=true;           shift ;;
        --force)             FORCE=true;               shift ;;
        --since)             SINCE="$2";               shift 2 ;;
        --org)               ORG="$2";                 shift 2 ;;
        *)                   echo "Unknown argument: $1"; exit 1 ;;
    esac
done

SINCE_ARGS=()
[[ -n "$SINCE" ]] && SINCE_ARGS=(--since "$SINCE")

ORG_ARGS=()
[[ -n "$ORG" ]] && ORG_ARGS=(--org "$ORG")

FORCE_ARG=()
[[ "$FORCE" == true ]] && FORCE_ARG=(--force)

CONFLUENCE_OK=false

echo "════════════════════════════════════════════════"
echo "  Collecting data for: $AUTHOR"
echo "════════════════════════════════════════════════"

# ── Fetch ─────────────────────────────────────────

echo ""
echo "── Fetch: PRs (parallel) ────────────────────────"
python3 "$SCRIPTS/fetch_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" "${ORG_ARGS[@]}" "${FORCE_ARG[@]}" &
PID_AUTHORED=$!
python3 "$SCRIPTS/fetch_reviewed_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" "${ORG_ARGS[@]}" "${FORCE_ARG[@]}" &
PID_REVIEWED=$!

wait $PID_AUTHORED || { echo "Error: fetch_prs.py failed"; exit 1; }
wait $PID_REVIEWED || { echo "Error: fetch_reviewed_prs.py failed"; exit 1; }

if [[ "$RUN_JIRA" == true ]]; then
    echo ""
    echo "── Fetch: JIRA strip ────────────────────────────"
    bash "$SCRIPTS/strip_jira.sh" --author "$AUTHOR"

    echo ""
    echo "── Fetch: Sprint Totals ─────────────────────────"
    python3 "$SCRIPTS/fetch_sprint_totals.py" --author "$AUTHOR" "${FORCE_ARG[@]}" \
        || echo "  Sprint totals unavailable — continuing without (check JIRA credentials in .env)."
fi

if [[ "$RUN_CONFLUENCE" == true ]]; then
    echo ""
    echo "── Fetch: Confluence ────────────────────────────"
    CONFLUENCE_EMAIL_ARGS=()
    [[ -n "$CONFLUENCE_EMAIL" ]] && CONFLUENCE_EMAIL_ARGS=(--confluence-email "$CONFLUENCE_EMAIL")
    if python3 "$SCRIPTS/fetch_confluence.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" "${FORCE_ARG[@]}" "${CONFLUENCE_EMAIL_ARGS[@]}"; then
        CONFLUENCE_OK=true
    else
        echo "  Confluence fetch failed — skipping analysis (check JIRA credentials in .env)."
    fi
fi

# ── Analyse ───────────────────────────────────────

echo ""
echo "── Analyse: PRs ─────────────────────────────────"
python3 "$SCRIPTS/analyse_prs.py" --author "$AUTHOR"

if [[ "$RUN_JIRA" == true ]]; then
    echo ""
    echo "── Analyse: JIRA ────────────────────────────────"
    python3 "$SCRIPTS/analyse_jira.py" --author "$AUTHOR"
fi

if [[ "$CONFLUENCE_OK" == true ]]; then
    echo ""
    echo "── Analyse: Confluence ──────────────────────────"
    python3 "$SCRIPTS/analyse_confluence.py" --author "$AUTHOR"
fi

# ── Export ────────────────────────────────────────

if [[ "$EXPORT_MD" == true ]]; then
    echo ""
    echo "── Export: Markdown ─────────────────────────────"
    python3 "$SCRIPTS/export_markdown.py" --author "$AUTHOR" "${SINCE_ARGS[@]}"
fi

echo ""
echo "════════════════════════════════════════════════"
echo "  Done. Files written to $REPO_ROOT/data/"
echo "    ${AUTHOR}_prs.json"
echo "    ${AUTHOR}_reviewed_prs.json"
if [[ "$RUN_JIRA" == true ]]; then
    echo "    ${AUTHOR}_jira.csv"
    [[ -f "data/${AUTHOR}_sprint_totals.json" ]] && echo "    ${AUTHOR}_sprint_totals.json"
fi
[[ -f "data/${AUTHOR}_confluence.json" ]] && echo "    ${AUTHOR}_confluence.json"
if [[ "$EXPORT_MD" == true ]]; then
    echo "    ${AUTHOR}_review.md"
fi
echo "════════════════════════════════════════════════"
