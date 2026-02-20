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
#   ./scripts/collect_author.sh <github-login> --jira --confluence --export-md
#   ./scripts/collect_author.sh <github-login> --force
#
# --jira        Strip JIRA.csv (from repo root) and analyse it.
#               Input:  JIRA.csv  (must exist in repo root)
#               Output: data/<author>_jira.csv
# --confluence  Fetch and analyse Confluence contributions (requires .env creds).
#               Output: data/<author>_confluence.json
# --export-md   Generate data/<author>_review.md after all steps succeed.
# --force       Re-fetch all data even if output files already exist.

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
RUN_JIRA=false
RUN_CONFLUENCE=false
EXPORT_MD=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jira)       RUN_JIRA=true;       shift ;;
        --confluence) RUN_CONFLUENCE=true; shift ;;
        --export-md)  EXPORT_MD=true;      shift ;;
        --force)      FORCE=true;          shift ;;
        --since)      SINCE="$2";          shift 2 ;;
        *)            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

SINCE_ARGS=()
[[ -n "$SINCE" ]] && SINCE_ARGS=(--since "$SINCE")

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

if [[ "$RUN_CONFLUENCE" == true ]]; then
    echo ""
    if [[ -n "${JIRA_TOKEN:-}" && -n "${JIRA_URL:-}" && -n "${JIRA_EMAIL:-}" ]]; then
        echo "── Confluence Fetch ─────────────────────────────"
        python3 "$SCRIPTS/fetch_confluence.py" --author "$AUTHOR" "${SINCE_ARGS[@]}" "${FORCE_ARG[@]}"
        echo ""
        echo "── Confluence Analysis ──────────────────────────"
        python3 "$SCRIPTS/analyse_confluence.py" --author "$AUTHOR"
    else
        echo "── Confluence ───────────────────────────────────"
        echo "  Skipped — set JIRA_TOKEN, JIRA_URL, JIRA_EMAIL in .env to enable."
    fi
fi

if [[ "$EXPORT_MD" == true ]]; then
    echo ""
    echo "── Markdown Export ──────────────────────────────"
    python3 "$SCRIPTS/export_markdown.py" --author "$AUTHOR" "${SINCE_ARGS[@]}"
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
if [[ "$RUN_CONFLUENCE" == true && -n "${JIRA_TOKEN:-}" && -n "${JIRA_URL:-}" && -n "${JIRA_EMAIL:-}" ]]; then
    echo "    ${AUTHOR}_confluence.json"
fi
if [[ "$EXPORT_MD" == true ]]; then
    echo "    ${AUTHOR}_review.md"
fi
echo "════════════════════════════════════════════════"
