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
#   ./scripts/collect_author.sh <github-login> --since 2025-01-01 --jira
#
# --jira  Strip JIRA.csv (from repo root) and analyse it.
#         Input:  JIRA.csv  (must exist in repo root)
#         Output: data/<author>_jira.csv

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <github-login> [--since YYYY-MM-DD] [--jira]"
    exit 1
fi

AUTHOR="$1"
shift

SINCE_ARGS=()
RUN_JIRA=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jira) RUN_JIRA=true; shift ;;
        *)      SINCE_ARGS+=("$1"); shift ;;
    esac
done

echo "════════════════════════════════════════════════"
echo "  Collecting data for: $AUTHOR"
echo "════════════════════════════════════════════════"

echo ""
echo "── Steps 1+2 (parallel): Fetching PRs ──────────"

python3 "$SCRIPTS/fetch_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" &
PID_AUTHORED=$!
python3 "$SCRIPTS/fetch_reviewed_prs.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" &
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
    echo "── Step 4: JIRA Strip + Analysis ───────────────"
    bash "$SCRIPTS/strip_jira.sh" --author "$AUTHOR"
    python3 "$SCRIPTS/analyse_jira.py" --author "$AUTHOR"
fi

echo ""
echo "════════════════════════════════════════════════"
echo "  Done. Files written to $REPO_ROOT/data/"
echo "    ${AUTHOR}_prs.json"
echo "    ${AUTHOR}_reviewed_prs.json"
if [[ "$RUN_JIRA" == true ]]; then
    echo "    ${AUTHOR}_jira.csv"
fi
echo "════════════════════════════════════════════════"
