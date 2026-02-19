#!/usr/bin/env bash
# scripts/collect_author.sh
#
# Fetch and analyse all PR data for a given GitHub author in one shot.
#
# Usage:
#   ./scripts/collect_author.sh <github-login>
#   ./scripts/collect_author.sh <github-login> --since 2025-01-01

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <github-login> [--since YYYY-MM-DD]"
  exit 1
fi

AUTHOR="$1"
shift
SINCE_ARG="${@}"  # pass any remaining args (e.g. --since) through to python scripts

echo "════════════════════════════════════════════════"
echo "  Collecting PR data for: $AUTHOR"
echo "════════════════════════════════════════════════"

echo ""
echo "── Steps 1+2 (parallel): Fetching PRs ──────────"

python3 "$SCRIPTS/fetch_prs.py"          --author "$AUTHOR" $SINCE_ARG &
PID_AUTHORED=$!
python3 "$SCRIPTS/fetch_reviewed_prs.py" --author "$AUTHOR" $SINCE_ARG &
PID_REVIEWED=$!

wait $PID_AUTHORED || { echo "Error: fetch_prs.py failed"; exit 1; }
wait $PID_REVIEWED || { echo "Error: fetch_reviewed_prs.py failed"; exit 1; }

echo ""
echo "── Step 3/3: Analysis ───────────────────────────"
python3 "$SCRIPTS/analyse_prs.py" --author "$AUTHOR"

echo "════════════════════════════════════════════════"
echo "  Done. Files written to $REPO_ROOT/data/"
echo "    ${AUTHOR}_prs.json"
echo "    ${AUTHOR}_reviewed_prs.json"
echo "════════════════════════════════════════════════"
