# Annual Review Toolkit

Scripts for generating quantitative data for an annual performance review.
Pulls GitHub PR activity, JIRA ticket work, and Confluence contributions into
a single Markdown report you can paste directly into Confluence or Notion.

**What you get:**
- PR counts, merge rate, code churn, time-to-merge, size distribution, reviewer breakdown
- JIRA ticket stats: issue types, priorities, story points, cycle time, epics
- Sprint contribution — your story points vs team total, per sprint
- Confluence pages created and edited, by space, content type, and activity timeline
- A single `data/<login>_review.md` export covering all three sections

---

## Dependencies

| Tool | Install | Used for |
|---|---|---|
| **Python 3.10+** | `brew install python` | All analysis scripts |
| **GitHub CLI (`gh`)** | `brew install gh` | Fetching PR data |

Verify:
```bash
python3 --version   # 3.10+
gh --version
```

---

## Setup

### 1. Authenticate the GitHub CLI

```bash
gh auth login
```

Select **GitHub.com** → **SSH** → follow prompts. Verify with:

```bash
gh auth status
```

The scripts use your authenticated identity automatically. To run for a different
person, pass `--author <github-login>` and `--email <atlassian-email>` (see [Running for a colleague](#running-for-a-colleague)).

### 2. Configure JIRA / Confluence credentials

Required for JIRA tickets, sprint contribution %, and Confluence analysis.
All three sections use the same Atlassian API token.

```bash
cp .env.example .env
```

```ini
# .env
JIRA_URL=https://your-org.atlassian.net
JIRA_EMAIL=you@your-org.com
JIRA_TOKEN=your-api-token-here
```

Get an API token at: **Atlassian account settings → Security → API tokens**

`.env` is gitignored — never commit it. The scripts read these values only from `.env` or the environment, so the token never appears on the command line.

---

## Quick Start

```bash
# GitHub PRs only
./scripts/collect_author.sh --git --org my-company --since 2025-01-01

# Everything: GitHub + JIRA + Confluence + Markdown export
./scripts/collect_author.sh --git --jira --confluence --org my-company --since 2025-01-01 --export-md

# JIRA only (no GitHub fetch needed)
./scripts/collect_author.sh --jira

# Re-fetch everything from scratch (ignore cache)
./scripts/collect_author.sh --git --jira --confluence --org my-company --since 2025-01-01 --export-md --force
```

**Flags:**

| Flag | Description |
|---|---|
| `--author <github-login>` | GitHub login of the person (default: the login `gh` is authenticated as). Names the GitHub files. |
| `--email <atlassian-email>` | Atlassian email of the person (default: `JIRA_EMAIL`). Names the JIRA and Confluence files. |
| `--git` | Fetch GitHub PRs (authored + reviewed) |
| `--org <github-org>` | Limit PR discovery to this GitHub org (e.g. `my-company`). Omit to include all orgs. |
| `--jira` | Fetch resolved JIRA tickets and sprint totals (requires `.env` credentials) |
| `--confluence` | Fetch Confluence contributions (requires `.env` credentials) |
| `--since YYYY-MM-DD` | Only include activity from this date onwards (default: `START_DATE` in `scripts/utils.py`) |
| `--export-md` | Generate `data/<login>_review.md` after all steps complete |
| `--force` | Re-fetch all data even if cached output files already exist |

Every script uses the same flags: the GitHub scripts take `--author`, the JIRA and Confluence scripts take `--email`, and `export_markdown.py` takes both. Every script that filters by date takes `--since` with the same default.

### Filtering by date (`--since`)

`--since` limits both the fetch and the analysis. The analyse scripts and `export_markdown.py` also accept `--since`, so you can narrow cached data without re-fetching.

| Source | Date field compared to `--since` |
|---|---|
| Authored PRs | PR `createdAt` |
| Reviewed PRs | your review's `submittedAt` (PRs with no review left after the filter are dropped) |
| JIRA tickets | `Resolved`, or `Created` when the ticket has no `Resolved` date |
| Confluence pages you created | page `created` |
| Confluence pages you edited | page `last_modified` |

Filtering cached data cannot add activity that the fetch skipped. When a cached file starts later than `--since`, the fetch script prints a warning and keeps the cache (pass `--force` to re-fetch). The PR fetch scripts record their start date in `data/<login>_prs.since` and `data/<login>_reviewed_prs.since`. The JIRA and Confluence JSON files store it in a `since` field. PR caches fetched before the `.since` files existed warn with an unknown date.

`fetch_reviewed_prs.py` searches for PRs updated on or after `--since`, so it finds PRs opened earlier that you reviewed later. It keeps only your reviews submitted on or after `--since`. Reviewed-PR caches fetched before this change searched by PR creation date and miss those PRs, so re-fetch them with `--force`.

Output files are written to `data/` (gitignored). GitHub files use the GitHub login. JIRA and Confluence files use `<name>`, the email before the `@`:
```
data/<login>_prs.json
data/<login>_reviewed_prs.json
data/<name>_jira.json               (--jira)
data/<name>_sprint_totals.json      (--jira, with .env credentials)
data/<name>_confluence.json         (--confluence)
data/<login>_review.md              (--export-md)
```

Caches from before this naming used `data/<login>_sprint_totals.json` and `data/<login>_confluence.json`. Rename them to the `<name>` prefix, or re-fetch with `--force`. The JIRA CSV export is no longer read. Run `fetch_jira.py` to create `data/<name>_jira.json`.

---

## GitHub PR Analysis

### What it measures

- **Authored PRs** — count, merge rate, code churn, time-to-merge, size distribution, reviewers
- **Reviewed PRs** — volume, verdicts given, authors reviewed

### Running manually

```bash
python3 scripts/fetch_prs.py --author <login> --org my-company --since 2025-01-01
python3 scripts/fetch_reviewed_prs.py --author <login> --org my-company --since 2025-01-01
python3 scripts/analyse_prs.py --author <login>
```

The default `--since` date is `START_DATE` in `scripts/utils.py` — update it for your
review period. Fetched data is cached in `data/`; re-running analysis is instant.

---

## JIRA Analysis

`fetch_jira.py` fetches tickets with status Done, resolved on or after `--since`, where the person is the assignee or the reporter. It skips the `Admin Access` and `Access Request` issue types, and writes `data/<name>_jira.json`. The file records the person's JIRA display name and account ID, and keeps every label and every sprint of each ticket. `analyse_jira.py` counts a ticket as yours when its assignee or reporter account ID matches.

```bash
python3 scripts/fetch_jira.py --since 2025-01-01
python3 scripts/fetch_sprint_totals.py
python3 scripts/analyse_jira.py
```

`fetch_sprint_totals.py` fetches team ticket and story point totals for each sprint in your tickets, so you can see your share of each sprint's completed work. It discovers the story points field from your JIRA instance.

Both files are cached in `data/`. Pass `--force` to re-fetch.

---

## Confluence Analysis

Fetches pages you created and pages you edited (others' pages). Produces a
breakdown by space, content type, and activity timeline, plus a version history
for pages you own.

Requires the same `.env` credentials used for JIRA.

```bash
python3 scripts/fetch_confluence.py --since 2025-01-01
python3 scripts/analyse_confluence.py
```

Data is cached in `data/<name>_confluence.json`. Pass `--force` to re-fetch.

---

## Exporting to Markdown

Generates a single Markdown file covering all three sections. Sections whose
data files are absent are skipped automatically.

```bash
python3 scripts/export_markdown.py --author <login> --since 2025-01-01
# → data/<login>_review.md
```

Bar charts from the terminal output are replaced with `%` columns in tables,
which render cleanly in any Markdown viewer.

**To paste into Confluence:** open the target page → `...` menu → **Edit** →
switch to **Markdown** editor → paste the file contents. All tables, headings,
and emphasis render natively.

---

## Running for a Colleague

You can use **your own API token** — no need to share credentials.

- **GitHub PRs** are scoped by `--author <github-login>`
- **JIRA** tickets and **Confluence** pages are fetched for whoever's email is passed via `--email`; your `.env` token is used for auth

```bash
./scripts/collect_author.sh \
  --author their-github-login \
  --email their-atlassian@your-org.com \
  --since 2025-01-01 \
  --jira \
  --confluence \
  --export-md
```

Output is written to `data/their-github-login_review.md`; all intermediate
files are scoped to their login or email name so your own cached data is unaffected.

---

## Caching

All fetch scripts write their output to `data/` and skip the network on
subsequent runs. Pass `--force` to any fetch script to re-fetch from the API.

`data/` is gitignored — all outputs are local only.
