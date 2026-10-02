"""Daily fetch job. Usage: PYTHONPATH=src python -m forecast_log [--dry-run]"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

from . import config, openmeteo, scoring, store

LEADS = 14  # lead 0 through lead 13
# One extra day so issued_date + 13 is still covered when the site-local date
# lags the UTC date (e.g. a manual run on a US evening).
FORECAST_DAYS = LEADS + 1


def build_rows(cfg, issued_date, fetch=openmeteo.fetch_members):
    """Fetch every site and score every target date. Raises on any failure."""
    rows = []
    for site in cfg.sites:
        members = fetch(site, cfg.model, FORECAST_DAYS)
        for lead in range(LEADS):
            target = issued_date + timedelta(days=lead)
            try:
                p, n = scoring.score_day(members, target, site.criteria)
            except ValueError as e:
                raise RuntimeError(f"{site.id}: {e}") from e
            rows.append(
                {
                    "issued_date": issued_date.isoformat(),
                    "site": site.id,
                    "target_date": target.isoformat(),
                    "p_flyable": p,
                    "n_members": n,
                    "criteria_version": cfg.criteria_version,
                }
            )
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog="forecast_log", description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="fetch and print, write nothing")
    ap.add_argument("--sites", default="sites.yaml")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args(argv)

    cfg = config.load(args.sites)
    issued = datetime.now(timezone.utc).date()
    try:
        rows = build_rows(cfg, issued)
    except (openmeteo.FetchError, RuntimeError) as e:
        print(f"error: {e}. Nothing written.", file=sys.stderr)
        return 1

    path = store.month_path(args.data_dir, issued.isoformat())
    if args.dry_run:
        print(f"# dry run: would write {len(rows)} rows for {issued} to {path}", file=sys.stderr)
        sys.stdout.write(store.format_rows(rows))
        return 0

    merged = store.merge(store.read_rows(path), rows, issued.isoformat())
    store.write_rows(path, merged)
    print(f"wrote {len(rows)} rows for {issued} to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
