"""Generate sites.yaml from sites.csv.

Usage: PYTHONPATH=src python -m forecast_log.sites [--csv sites.csv] [--yaml sites.yaml]

sites.csv is the hand-edited source (spreadsheet-friendly). This script:
  - fills blank `timezone` cells by looking up the coordinates (and writes
    them back into sites.csv so you can see them),
  - bumps criteria_version if any existing site's location, timezone or
    criteria changed (adding or removing a site does not bump it),
  - validates everything, then rewrites sites.yaml.
`model` and `criteria_version` are carried over from the existing sites.yaml.
"""

import argparse
import csv
import json
import sys
import urllib.parse
from pathlib import Path

import yaml

from . import config, openmeteo

CSV_COLUMNS = [
    "id", "name", "lat", "lon", "timezone", "dir_ranges",
    "speed_min", "speed_max", "gust_max", "rain_mm_max",
    "fly_start", "fly_end", "min_hours", "placeholder", "notes",
]  # fmt: skip
DEFAULT_MODEL = "gfs_seamless"

HEADER = """\
# GENERATED from sites.csv by `python -m forecast_log.sites`. Do not edit by
# hand: edit sites.csv instead. Only `model` may be edited here (bump
# criteria_version yourself if you change it).
#
# criteria_version is bumped automatically when an existing site's location,
# timezone or criteria change, so past probabilities stay comparable.
#
# Units: wind speeds and gusts in mph, precipitation in mm per hour,
# wind direction in degrees (direction the wind blows FROM, 0 = N, 90 = E).
#
# A day is flyable for one ensemble member when at least `min_consecutive_hours`
# consecutive hours inside the flying window (site-local time) all satisfy:
#   wind_speed_min <= speed <= wind_speed_max
#   gust <= gust_max
#   direction inside any range in wind_dir_ranges (ranges may wrap through
#     north, e.g. [340, 20])
#   precipitation <= precip_max
# The flying window covers hours starting at flying_hours[0] up to, but not
# including, flying_hours[1]. [10, 18] means 10:00 through 17:59.
#
# A site with `placeholder: true` blocks the job from writing data
# (--dry-run still works).
"""


def parse_dir_ranges(text: str):
    """'255-285' or '340-20; 90-110' -> [(255, 285)] / [(340, 20), (90, 110)]."""
    ranges = []
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        lo, sep, hi = part.partition("-")
        if not sep:
            raise ValueError(f"wind direction range {part!r} must look like 255-285")
        lo, hi = _num(lo), _num(hi)
        for d in (lo, hi):
            if not 0 <= d <= 360:
                raise ValueError(f"wind direction {d} out of 0-360 in {part!r}")
        ranges.append((lo, hi))
    if not ranges:
        raise ValueError("dir_ranges is empty")
    return ranges


def _num(text):
    f = float(str(text).strip())
    return int(f) if f.is_integer() else f


def _bool(text):
    t = str(text).strip().lower()
    if t in ("", "no", "n", "false", "0"):
        return False
    if t in ("yes", "y", "true", "1", "x"):
        return True
    raise ValueError(f"placeholder must be yes/no, got {text!r}")


def read_csv(path):
    # utf-8-sig strips the BOM Excel adds when saving "CSV UTF-8".
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(missing)}")
        rows = [r for r in reader if any((v or "").strip() for v in r.values())]
        return rows, reader.fieldnames


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def row_to_site(row, line):
    """One CSV row -> sites.yaml site dict. `line` is used in error messages."""
    try:
        sid = row["id"].strip()
        if not sid:
            raise ValueError("id is empty")
        return {
            "id": sid,
            "name": row["name"].strip() or sid,
            "placeholder": _bool(row["placeholder"]),
            "lat": _num(row["lat"]),
            "lon": _num(row["lon"]),
            "timezone": row["timezone"].strip(),
            "criteria": {
                "wind_speed_min": _num(row["speed_min"]),
                "wind_speed_max": _num(row["speed_max"]),
                "gust_max": _num(row["gust_max"]),
                "wind_dir_ranges": parse_dir_ranges(row["dir_ranges"]),
                "precip_max": _num(row["rain_mm_max"]),
                "flying_hours": [int(_num(row["fly_start"])), int(_num(row["fly_end"]))],
                "min_consecutive_hours": int(_num(row["min_hours"])),
            },
            "notes": " ".join((row.get("notes") or "").split()),
        }
    except ValueError as e:
        raise ValueError(f"sites.csv line {line}: {e}") from e


def _fingerprint(site: dict):
    """What, if changed, makes old and new p_flyable for a site incomparable."""
    return (
        float(site["lat"]),
        float(site["lon"]),
        site["timezone"],
        config.parse_criteria(site["criteria"], site["id"]),
    )


def next_version(old_raw, new_sites):
    """(criteria_version, changed_ids): old + 1 if any existing site changed."""
    if not old_raw:
        return 1, []
    old = {s["id"]: _fingerprint(s) for s in old_raw.get("sites") or []}
    changed = [s["id"] for s in new_sites if s["id"] in old and old[s["id"]] != _fingerprint(s)]
    version = old_raw["criteria_version"]
    return (version + 1, changed) if changed else (version, [])


def _fmt(v):
    if isinstance(v, str):
        return json.dumps(v)  # a JSON string is a valid YAML double-quoted scalar
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return str(v)


def render_yaml(version, model, sites) -> str:
    out = [HEADER, f"criteria_version: {version}", "", f"model: {_fmt(model)}", "", "sites:"]
    for s in sites:
        out.append(f"  - id: {_fmt(s['id'])}")
        if s["notes"]:
            out.append(f"    # {s['notes']}")
        out.append(f"    name: {_fmt(s['name'])}")
        if s["placeholder"]:
            out.append("    placeholder: true")
        for k in ("lat", "lon", "timezone"):
            out.append(f"    {k}: {_fmt(s[k])}")
        out.append("    criteria:")
        for k, v in s["criteria"].items():
            out.append(f"      {k}: {_fmt(v)}")
        out.append("")
    return "\n".join(out)


def lookup_timezone(lat, lon):
    params = urllib.parse.urlencode(
        {"latitude": lat, "longitude": lon, "timezone": "auto", "hourly": "temperature_2m",
         "forecast_days": 1}  # fmt: skip
    )
    return openmeteo._get_json(f"https://api.open-meteo.com/v1/forecast?{params}")["timezone"]


def generate(csv_path, yaml_path, lookup=lookup_timezone, log=print):
    """Returns (yaml_text, csv_rows_changed). Writes nothing."""
    rows, _ = read_csv(csv_path)
    csv_changed = False
    for row in rows:
        if not row["timezone"].strip():
            row["timezone"] = lookup(row["lat"].strip(), row["lon"].strip())
            log(f"{row['id']}: looked up timezone {row['timezone']}")
            csv_changed = True
    sites = [row_to_site(r, i) for i, r in enumerate(rows, start=2)]

    old_raw = None
    if Path(yaml_path).exists():
        with open(yaml_path, encoding="utf-8") as f:
            old_raw = yaml.safe_load(f)
    model = (old_raw or {}).get("model") or DEFAULT_MODEL
    version, changed = next_version(old_raw, sites)
    if changed:
        log(f"criteria changed for {', '.join(changed)}: criteria_version -> {version}")

    text = render_yaml(version, model, sites)
    config.parse(yaml.safe_load(text))  # full validation before anything is written
    return text, rows if csv_changed else None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="forecast_log.sites", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="sites.csv")
    ap.add_argument("--yaml", default="sites.yaml")
    args = ap.parse_args(argv)
    try:
        text, new_rows = generate(args.csv, args.yaml, log=lambda m: print(m, file=sys.stderr))
    except (ValueError, KeyError, openmeteo.FetchError) as e:
        print(f"error: {e}. Nothing written.", file=sys.stderr)
        return 1
    if new_rows is not None:
        write_csv(args.csv, new_rows, read_csv(args.csv)[1])
        print(f"updated {args.csv} (timezones filled in)", file=sys.stderr)
    old = Path(args.yaml).read_text(encoding="utf-8") if Path(args.yaml).exists() else None
    if text != old:
        Path(args.yaml).write_text(text, encoding="utf-8")
        print(f"wrote {args.yaml}", file=sys.stderr)
    else:
        print(f"{args.yaml} already up to date", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
