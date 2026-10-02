# flyorfold/forecast-log

Once a day, this job takes a snapshot of FlyOrFold's **probability of flyable paragliding conditions** (`p_flyable`) for each site, for each of the next 14 days, and appends it to a CSV log. A day's forecast is gone once the day arrives, so the snapshot has to be taken in advance. The accumulated log is what later lets us check whether past forecasts were any good.

The dashboard lives in [`flyorfold.github.io`](https://github.com/flyorfold/flyorfold.github.io) and reads the CSVs from this repo.

## How it works

1. `sites.yaml` defines each site (id, coordinates, timezone) and its flyable criteria.
2. For each site, the job fetches an hourly **ensemble** forecast from the [Open-Meteo Ensemble API](https://open-meteo.com/en/docs/ensemble-api). The default model is `gfs_seamless`, which has 31 members (the control run plus 30 perturbed members).
3. Each member counts as flyable on a target date if it has at least `min_consecutive_hours` consecutive hours inside the site's flying window (site-local time) that all meet the criteria: wind speed range, gust limit, wind direction ranges, and precipitation limit.
4. `p_flyable` is the fraction of members that are flyable. Members missing any data in the window are left out, and `n_members` records how many were counted.
5. The job writes rows for target dates from issued date + 0 through + 13, then commits.

The scoring logic is a pure function in `src/forecast_log/scoring.py`, with unit tests.

## Data

One file per month of the **issued** date: `data/forecasts/YYYY-MM.csv`.

```
issued_date,site,target_date,p_flyable,n_members,criteria_version
2026-10-03,some-site,2026-10-04,0.62,31,1
```

| column | meaning |
|---|---|
| `issued_date` | UTC date the job ran (`YYYY-MM-DD`) |
| `site` | site id from `sites.yaml` |
| `target_date` | site-local date being forecast (`YYYY-MM-DD`) |
| `p_flyable` | 0–1, rounded to 3 decimals |
| `n_members` | ensemble members that contributed |
| `criteria_version` | from `sites.yaml`; compare probabilities only within one version |

Lead time is `target_date − issued_date` (0–13). It is derived, not stored.

Guarantees:
- **Unique key:** `(issued_date, site, target_date)`. Re-running on the same day replaces that day's rows and never adds duplicates.
- **Append-only:** rows from earlier issued dates are never changed or removed.
- **All-or-nothing:** if any site fails after retries, the job exits non-zero and writes nothing.

> **Schema changes are breaking for the dashboard.** New columns go at the end, and existing ones are never reordered or renamed.

Weather data comes from [Open-Meteo.com](https://open-meteo.com/) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The free API is for non-commercial use only.

## Configuring sites

**Edit `sites.csv`, not `sites.yaml`.** The CSV is the spreadsheet-friendly source. `sites.yaml` is generated from it, and the fetch job reads the YAML.

1. Open `sites.csv` in Excel, Numbers or Google Sheets, then save or export it as CSV.
2. Commit and push it, either locally or with *Add file → Upload files* on GitHub.
3. The `sync-sites` workflow runs automatically. It regenerates `sites.yaml` and commits it as `github-actions[bot]`. If you pushed from your machine, run `git pull` afterwards.

You can also run the generator locally to check your edits before pushing:

```bash
PYTHONPATH=src .venv/bin/python -m forecast_log.sites
```

Columns (units: mph, mm per hour, degrees the wind blows **from**, site-local hours):

| column | example | meaning |
|---|---|---|
| `id` | `lake-erie-cleveland` | stable id that appears in the data; never rename it once data is logged |
| `name` | `Lake Erie ridge, Cleveland` | display name |
| `lat`, `lon` | `41.4873`, `-81.7477` | launch coordinates |
| `timezone` | `America/New_York` | **leave blank** and it is looked up from the coordinates and written back into the CSV |
| `dir_ranges` | `340-20` or `255-285; 300-320` | allowed wind directions; a range may wrap through north |
| `speed_min`, `speed_max` | `5`, `15` | wind speed range in mph, inclusive |
| `gust_max` | `18` | max gust in mph |
| `rain_mm_max` | `0.1` | max precipitation per hour in mm |
| `fly_start`, `fly_end` | `10`, `18` | flying window; `10`–`18` means 10:00 through 17:59 |
| `min_hours` | `2` | consecutive qualifying hours needed for the day to count as flyable |
| `placeholder` | `yes` or blank | `yes` blocks the job from writing data until the site is finalized |
| `notes` | | free text; copied into `sites.yaml` as a comment |

`criteria_version` is **bumped automatically** when an existing site's coordinates, timezone or criteria change. Adding a site, removing one, or editing names and notes does not bump it. `model` is the only setting edited directly in `sites.yaml`. If you change it, bump `criteria_version` by hand.

If any site has `placeholder` set, the job refuses to write data (dry runs still work), so the scheduled workflow **fails on purpose** until the flag is cleared. A test also fails if `sites.yaml` is out of date with `sites.csv`.

Each site's `timezone` decides what "day" means for its target dates. Get it right for the launch itself, not the nearest city. For example, the Tennessee launch is on Central time even though Chattanooga is on Eastern.

## Running locally

Requires Python 3.10+.

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

Dry run, which fetches and prints CSV to stdout without touching any files:

```bash
PYTHONPATH=src .venv/bin/python -m forecast_log --dry-run
```

Real run, which writes to `data/forecasts/`:

```bash
PYTHONPATH=src .venv/bin/python -m forecast_log
```

Tests:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

Don't commit data from local runs. Data should come from the workflow, or from an explicit, reviewed backfill.

## GitHub Actions

`.github/workflows/fetch-forecasts.yml` runs daily at **10:30 UTC** and can also be started by hand from the Actions tab (*Run workflow*, with an optional dry-run checkbox). It runs the tests, fetches, and commits `data/` as `github-actions[bot]` only if something changed. A concurrency group stops two runs from racing.

### Scheduled-workflow auto-disable

GitHub automatically disables scheduled workflows in a **public** repository after **60 days with no repository activity**. The daily data commits normally count as activity. If the job keeps failing (for example, while the placeholder sites are still in place), there will be no commits, and the schedule will be disabled after 60 days. GitHub sends a warning email beforehand. To turn it back on, open *Actions → fetch-forecasts → Enable workflow*, or run:

```bash
gh workflow enable fetch-forecasts.yml --repo flyorfold/forecast-log
```

Any push to the repo also resets the 60-day clock.
