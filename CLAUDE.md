# CLAUDE.md — flyorfold/forecast-log

## What this repo is

A data-logging repo for **FlyOrFold**, a hobby tool that answers: *"What is the probability of flyable paragliding conditions at site S, N days from now?"*

This repo does one job: **once a day, capture the forecast probability for each site for each of the next 14 days, and append it to a log.** The forecast for a given day is overwritten and lost once that day arrives, so the snapshot has to be taken in advance. The accumulated log is what later lets us verify whether past forecasts were any good.

Related repos in the `flyorfold` GitHub org:
- `flyorfold.github.io` — the Pages site and dashboard. It **reads** data from this repo. No site or dashboard code belongs here.

## Core concepts

- **Site**: a paragliding launch (about 6, in or near Ohio). Defined in `sites.yaml`.
- **Flyable**: whether conditions at a site meet that site's criteria on a given day. Criteria live in `sites.yaml` (wind speed range, wind direction range, gust limit, precipitation, flying-hours window). Do not hardcode criteria in code.
- **Probability of flyable (`p_flyable`)**: from an **ensemble** forecast, the fraction of ensemble members for which the day is flyable under the site's criteria. A single deterministic forecast yields only 0 or 1, which is not a probability, so use ensemble data.
- **Issued date**: the (UTC) date the job ran. **Target date**: the (site-local) date being forecast. **Lead time** = target − issued, and is derived, not stored.

## Data schema

Forecast log, appended daily, one file per month: `data/forecasts/YYYY-MM.csv` (month of the *issued* date).

```
issued_date,site,target_date,p_flyable,n_members,criteria_version
2026-10-03,<site-id>,2026-10-04,0.62,30,1
```

- One row per site per target date per run. About 6 sites × 14 days ≈ 84 rows/day.
- `p_flyable`: float 0–1, rounded to 3 decimals.
- `n_members`: how many ensemble members contributed.
- `criteria_version`: integer from `sites.yaml`. Bump it whenever a site's criteria change, so past probabilities stay comparable.
- Include the target dates from issued_date (lead 0) through issued_date + 13 (lead 13).

Reserved for later (do not build yet): `data/outcomes/YYYY-MM.csv` with `site,date,flew,source`, where `source` is `weather` (derived from observed or reanalysis data) or `manual` (pilot log). Verification and the dashboard are out of scope for this repo's v1.

## Behavior requirements for the fetch job

- **Idempotent.** Re-running on the same day must not create duplicate rows. Key on `(issued_date, site, target_date)`. If rows already exist for today, replace them or skip, but never append duplicates.
- **Append-only history.** Never rewrite or delete rows from prior issued dates.
- **All-or-nothing per run.** If any site's fetch fails after retries, exit non-zero and write nothing partial. A loud failure is better than a silently incomplete day.
- **Retries** with backoff on network errors. Keep timeouts short. Do not retry forever.
- **Timezones.** Interpret "day" in the site's local timezone (`America/New_York` for Ohio sites). Store dates as ISO `YYYY-MM-DD`. `issued_date` is the UTC date of the run.
- **Deterministic and testable.** Keep the scoring logic (ensemble members + criteria → `p_flyable`) as a pure function with unit tests, separate from the HTTP and file I/O code.
- Provide a `--dry-run` mode that fetches and prints what would be written without touching files.

## Data source

Planned: **Open-Meteo**'s ensemble forecast API (no API key, as far as I know). Verify the current endpoints, model names, and free-tier terms in their docs before coding. Do not guess parameter names. If the source needs a key, it goes in GitHub Actions secrets and never into the repo.

## GitHub Actions workflow

- File: `.github/workflows/fetch-forecasts.yml`.
- Triggers: a daily `schedule` cron (UTC; pick a time after the morning model runs have published) **and** `workflow_dispatch` for manual runs.
- `permissions: contents: write` so the job can commit its own output, and nothing broader.
- Use a `concurrency` group so two runs can't race.
- Commit only if the data files changed. Commit as a bot with a message like `data: forecasts for 2026-10-03`.
- Pin third-party actions to a version (a full commit SHA is better).
- Note: GitHub can auto-disable scheduled workflows in a repo after a long period without activity (about 60 days, as far as I know). Check the current rules, and if it applies, document the workaround in the README.

## Repo layout

```
.
├── CLAUDE.md
├── README.md
├── sites.csv                  # hand-edited site list (spreadsheet); source for sites.yaml
├── sites.yaml                 # GENERATED from sites.csv: ids, lat/lon, timezone, criteria, criteria_version
├── src/                       # fetch + scoring code
├── tests/                     # unit tests for scoring and dedupe logic
├── data/
│   └── forecasts/YYYY-MM.csv  # append-only daily log
└── .github/workflows/
    └── fetch-forecasts.yml
```

## Conventions

- Keep it small. Prefer the standard library and few dependencies. This is a hobby project, so avoid frameworks and over-engineering.
- No secrets, tokens, or personal data in the repo.
- Never hand-edit files in `data/` as part of code changes. Data is written only by the job (or by an explicit, reviewed backfill).
- Write a clear README covering how to run locally, how to run a dry run, and how the data is structured, since the dashboard repo will depend on the schema.
- Changing the CSV schema is a breaking change for the dashboard. Call it out explicitly and prefer adding columns at the end over reordering.

## Open decisions — ask the owner, don't assume

1. **Language/runtime**: Python script vs. a .NET console app. Not yet chosen.
2. **Flyable criteria values** per site (wind ranges, direction windows, gust limits, flying-hours window, and how many consecutive qualifying hours make a day "flyable"). The owner is a paraglider and will supply these. Use clearly marked placeholders until then.
3. **Site list**: ids, coordinates, and timezones. The owner will supply them.
4. **Run time** of the daily cron.
