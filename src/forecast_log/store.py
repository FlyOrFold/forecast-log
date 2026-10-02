"""CSV log storage: one file per issued month, append-only across issued dates."""

import csv
import io
import os
import tempfile
from pathlib import Path

COLUMNS = ["issued_date", "site", "target_date", "p_flyable", "n_members", "criteria_version"]


def month_path(data_dir, issued_date: str) -> Path:
    return Path(data_dir) / "forecasts" / f"{issued_date[:7]}.csv"


def merge(existing, new, issued_date: str):
    """Pure merge of existing rows with today's rows.

    Rows from prior issued dates are kept exactly as they are and in order.
    Any existing rows for `issued_date` are replaced by `new`, so a re-run
    never duplicates. Raises ValueError if `new` contains other issued dates
    or duplicate keys.
    """
    keys = set()
    for r in new:
        if r["issued_date"] != issued_date:
            raise ValueError(f"new row has issued_date {r['issued_date']}, expected {issued_date}")
        k = (r["issued_date"], r["site"], r["target_date"])
        if k in keys:
            raise ValueError(f"duplicate key in new rows: {k}")
        keys.add(k)
    kept = [r for r in existing if r["issued_date"] != issued_date]
    return kept + list(new)


def format_rows(rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r[c] for c in COLUMNS})
    return buf.getvalue()


def read_rows(path: Path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path}: unexpected header {reader.fieldnames}")
        return list(reader)


def write_rows(path: Path, rows):
    """Write atomically, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(format_rows(rows))
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
