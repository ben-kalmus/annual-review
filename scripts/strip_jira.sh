#!/usr/bin/env bash
# scripts/strip_jira.sh
#
# Strip irrelevant columns from JIRA.csv using miller (mlr).
# JIRA exports have ~1,000 columns; this keeps only the fields
# useful for the annual performance review.
#
# Usage:
#   ./scripts/strip_jira.sh --author <login>                   # output: data/<login>_jira.csv
#   ./scripts/strip_jira.sh --author <login> --input JIRA.csv  # custom input
#   ./scripts/strip_jira.sh --input JIRA.csv --output data/out.csv  # fully custom
#
# Requires: mlr (miller), python3

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

AUTHOR=""
INPUT="$REPO_ROOT/JIRA.csv"
OUTPUT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --author) AUTHOR="$2"; shift 2 ;;
        --input)  INPUT="$2";  shift 2 ;;
        --output) OUTPUT="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

if [[ -z "$OUTPUT" ]]; then
    if [[ -n "$AUTHOR" ]]; then
        OUTPUT="$REPO_ROOT/data/${AUTHOR}_jira.csv"
    else
        OUTPUT="$REPO_ROOT/data/jira_stripped.csv"
    fi
fi

mkdir -p "$(dirname "$OUTPUT")"

# Columns to keep (using deduplicated names — duplicate headers in the
# original CSV get _2, _3 ... suffixes via scripts/dedup_csv_headers.py)
FIELDS=(
  # Core identity
  "Summary"
  "Issue key"
  "Issue Type"
  "Status"
  "Status Category"
  "Project key"
  "Priority"

  # People
  "Assignee"
  "Reporter"

  # Dates
  "Created"
  "Resolved"

  # Classification
  "Labels"
  "Labels_2"
  "Sprint"
  "Sprint_2"
  "Sprint_3"

  # Effort / sizing (Story point estimate, Actual Story Points, T-shirt size
  # are empty in current export; Story Points is 88% populated)
  "Custom field (Story Points)"

  # Hierarchy — Parent summary is the effective epic name in this export
  "Parent key"
  "Parent summary"

  # Content / narrative
  "Description"
)

# Join the array into a comma-separated string for mlr -f
FIELDS_CSV=$(IFS=,; echo "${FIELDS[*]}")

echo "Stripping columns from: $INPUT"
echo "Writing to:             $OUTPUT"

python3 "$REPO_ROOT/scripts/dedup_csv_headers.py" "$INPUT" \
  | mlr --csv --allow-ragged-csv-input cut -f "$FIELDS_CSV" \
  > "$OUTPUT"

ROW_COUNT=$(mlr --csv count "$OUTPUT" | mlr --csv cut -f count | tail -n1)
echo "Done. $ROW_COUNT rows, $(echo "${#FIELDS[@]}") columns → $OUTPUT"
