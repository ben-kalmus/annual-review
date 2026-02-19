#!/usr/bin/env bash
# scripts/collect_author.sh
#
# Fetch and analyse all PR (and optionally JIRA) data for a given GitHub
# author in one shot.
#
# Usage:
#   ./scripts/collect_author.sh <github-login>
#   ./scripts/collect_author.sh <github-login> --since 2025-01-01
#   ./scripts/collect_author.sh <github-login> --jira
#   ./scripts/collect_author.sh <github-login> --force
#   ./scripts/collect_author.sh <github-login> --since 2025-01-01 --jira --force
#
# --jira   Strip JIRA.csv (from repo root) and analyse it.
#          Input:  JIRA.csv  (must exist in repo root)
#          Output: data/<author>_jira.csv
# --force  Re-fetch all data even if output files already exist.

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
    echo "Usage: $0 <github-login> [--since YYYY-MM-DD] [--jira] [--force]"
    exit 1
fi

AUTHOR="$1"
shift

SINCE_ARGS=()
RUN_JIRA=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jira)  RUN_JIRA=true; shift ;;
        --force) FORCE=true;    shift ;;
        *)       SINCE_ARGS+=("$1"); shift ;;
    esac
done

FORCE_ARG=()
[[ "$FORCE" == true ]] && FORCE_ARG=(--force)

echo "════════════════════════════════════════════════"
echo "  Collecting data for: $AUTHOR"
echo "════════════════════════════════════════════════"

echo ""
echo "── Steps 1+2 (parallel): Fetching PRs ──────────"

python3 "$SCRIPTS/fetch_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" "${FORCE_ARG[@]}" &
PID_AUTHORED=$!
python3 "$SCRIPTS/fetch_reviewed_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" "${FORCE_ARG[@]}" &
PID_REVIEWED=$!

wait $PID_AUTHORED || {
    echo "Error: fetch_prs.py failed"
    exit 1
}
wait $PID_REVIEWED || {
    echo "Error: fetch_reviewed_prs.py failed"
    exit 1
}

echo ""
echo "── Step 3: PR Analysis ──────────────────────────"
python3 "$SCRIPTS/analyse_prs.py" --author "$AUTHOR"

if [[ "$RUN_JIRA" == true ]]; then
    echo ""
    echo "── Step 4: JIRA Strip ───────────────────────────"
    bash "$SCRIPTS/strip_jira.sh" --author "$AUTHOR"

    echo ""
    if [[ -n "${JIRA_TOKEN:-}" ]]; then
        if [[ -z "${JIRA_URL:-}" || -z "${JIRA_EMAIL:-}" ]]; then
            echo "── Step 5: Sprint Totals ─────────────────────────"
            echo "  Warning: JIRA_TOKEN is set but JIRA_URL or JIRA_EMAIL is missing — skipping."
            echo ""
            echo "── Step 5: JIRA Analysis ────────────────────────"
            python3 "$SCRIPTS/analyse_jira.py" --author "$AUTHOR"
        else
            echo "── Step 5: Fetch Sprint Totals (JIRA API) ───────"
            python3 "$SCRIPTS/fetch_sprint_totals.py" --author "$AUTHOR" "${FORCE_ARG[@]}"
            echo ""
            echo "── Step 6: JIRA Analysis ────────────────────────"
            python3 "$SCRIPTS/analyse_jira.py" --author "$AUTHOR"
        fi
    else
        echo "── Step 5: Sprint Totals ─────────────────────────"
        echo "  Skipped — set JIRA_TOKEN, JIRA_URL, JIRA_EMAIL to enable contribution %."
        echo ""
        echo "── Step 5: JIRA Analysis ────────────────────────"
        python3 "$SCRIPTS/analyse_jira.py" --author "$AUTHOR"
    fi
fi

echo ""
echo "════════════════════════════════════════════════"
echo "  Done. Files written to $REPO_ROOT/data/"
echo "    ${AUTHOR}_prs.json"
echo "    ${AUTHOR}_reviewed_prs.json"
if [[ "$RUN_JIRA" == true ]]; then
    echo "    ${AUTHOR}_jira.csv"
    if [[ -n "${JIRA_TOKEN:-}" && -n "${JIRA_URL:-}" && -n "${JIRA_EMAIL:-}" ]]; then
        echo "    ${AUTHOR}_sprint_totals.json"
    fi
fi
echo "════════════════════════════════════════════════"
