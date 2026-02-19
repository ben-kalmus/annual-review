# Annual Review Toolkit

Scripts for generating quantitative data for a GitHub/JIRA-based annual performance review.
Covers GitHub PR activity, JIRA ticket work, and Confluence contributions.

---

## Dependencies

| Tool | Install | Used for |
|---|---|---|
| **Python 3.10+** | `brew install python` | All analysis scripts |
| **GitHub CLI (`gh`)** | `brew install gh` | Fetching PR data |
| **Miller (`mlr`)** | `brew install miller` | Stripping JIRA CSV columns |

Verify everything is available:
```bash
python3 --version   # 3.10+
gh --version
mlr --version
```

---

## Setup

### 1. Authenticate GitHub CLI

```bash
gh auth login
```

Select **GitHub.com** → **SSH** → follow prompts. Verify with:

```bash
gh auth status
```

The scripts use your authenticated identity automatically. To run analysis for a different
person, pass `--author <github-login>` — they need to be a member of the org.

### 2. Configure JIRA credentials (optional — for sprint contribution %)

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

```ini
# .env
JIRA_URL=https://your-org.atlassian.net
JIRA_EMAIL=you@your-org.com
JIRA_TOKEN=your-api-token-here

# Story points custom field — run fetch_sprint_totals.py once to auto-discover
JIRA_SP_FIELD=customfield_10016
```

Get a JIRA API token at: **Atlassian account settings → Security → API tokens**

`.env` is gitignored — never commit it.

---

## Quick Start (everything in one command)

```bash
# GitHub PRs only
./scripts/collect_author.sh <github-login>

# GitHub PRs + JIRA analysis (requires JIRA.csv in repo root — see below)
./scripts/collect_author.sh <github-login> --jira

# Limit to a date range
./scripts/collect_author.sh <github-login> --since 2025-01-01

# Re-fetch everything (ignore cache)
./scripts/collect_author.sh <github-login> --jira --force
```

Output files are written to `data/`:
```
data/<login>_prs.json
data/<login>_reviewed_prs.json
data/<login>_jira.csv          (if --jira)
data/<login>_sprint_totals.json (if JIRA credentials set)
```

---

## GitHub PR Analysis

### What it measures

- PRs authored: count, merge rate, code churn (additions/deletions), files changed
- PRs reviewed: volume, repos covered, turnaround
- Repo breakdown and time-to-merge distribution

### Fetching and analysing

```bash
# Fetch authored PRs
python3 scripts/fetch_prs.py --author <login> --since 2025-05-28

# Fetch PRs reviewed by this person
python3 scripts/fetch_reviewed_prs.py --author <login> --since 2025-05-28

# Analyse (reads from data/ automatically)
python3 scripts/analyse_prs.py --author <login>
```

`--since` defaults to `2025-05-28` (set in `scripts/pr_utils.py` — update for your start date).

Fetched data is cached in `data/`. Re-running analysis is instant. Pass `--force` to re-fetch
from the API.

---

## JIRA Analysis

### Step 1 — Export your tickets from the JIRA UI

1. Open JIRA and go to **Issues → Advanced issue search**
2. Switch to **JQL mode** (top-right of the search bar)
3. Paste the query from `queries/completed-tickets.jql`:
   ```jql
   (assignee = currentUser() OR reporter = currentUser())
     AND status = Done
     AND resolutiondate >= "2025-05-28"
     AND issuetype NOT IN ("Admin Access", "Access Request")
   ORDER BY resolutiondate ASC
   ```
   Adjust the date to your review start date.
4. Click **Export** (top-right) → **Export CSV (all fields)**
5. Save the file as **`JIRA.csv`** in the repo root

> **Tip:** "All fields" is important — the strip script selects the relevant columns
> from the full export. A partial export may be missing Sprint or Story Points.


![Instruction image](assets/jira_help.png)

### Step 2 — Strip and analyse

```bash
# Strip irrelevant columns (requires mlr)
bash scripts/strip_jira.sh --author <login>

# Analyse ticket stats
python3 scripts/analyse_jira.py --author <login>
```

### Step 3 — Sprint contribution % (optional, requires JIRA credentials in .env)

Fetches the total team ticket count per sprint from the JIRA API so you can see
your share of each sprint's completed work.

```bash
python3 scripts/fetch_sprint_totals.py --author <login>
python3 scripts/analyse_jira.py --author <login>   # re-run to pick up totals
```

Sprint totals are cached in `data/<login>_sprint_totals.json`. Pass `--force` to re-fetch.

---

## Confluence Analysis (optional)

Fetches pages you created and pages you edited (others' pages), with breakdown by space,
content type, activity timeline, and version history.

Requires JIRA credentials in `.env` (same token works for Confluence).

```bash
python3 scripts/fetch_confluence.py --author <login>
python3 scripts/analyse_confluence.py --author <login>
```

Adjust `--since` to control the date window (default: `2025-05-28`).

---

## Running for a Colleague

All fetch scripts accept `--author <github-login>`. The GitHub CLI must be authenticated
with an account that has org read access. JIRA/Confluence fetches use `currentUser()` and
therefore always reflect the credentials in `.env` — to analyse a colleague's JIRA data
you would need them to export their own `JIRA.csv` and run the fetch scripts themselves.

```bash
./scripts/collect_author.sh their-github-login --since 2025-01-01
```

---

## Script Reference

| Script | Description |
|---|---|
| `collect_author.sh` | One-shot orchestrator — runs all steps in order |
| `fetch_prs.py` | Fetch authored PRs via GitHub CLI |
| `fetch_reviewed_prs.py` | Fetch reviewed PRs via GitHub CLI |
| `analyse_prs.py` | Analyse PR JSON → print summary |
| `strip_jira.sh` | Strip JIRA CSV to relevant columns (requires `mlr`) |
| `fetch_sprint_totals.py` | Fetch team sprint totals from JIRA API |
| `analyse_jira.py` | Analyse stripped JIRA CSV → print summary |
| `fetch_confluence.py` | Fetch Confluence page contributions via API |
| `analyse_confluence.py` | Analyse Confluence JSON → print summary |

---

## Caching

All fetch scripts cache their output in `data/` and skip the network on subsequent runs.
Pass `--force` to any fetch script to re-fetch from the API.

`data/` is gitignored — outputs are local only.
