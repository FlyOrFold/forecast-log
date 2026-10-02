import tempfile
import unittest
from pathlib import Path

from forecast_log import store


def row(issued, site, target, p=0.5):
    return {
        "issued_date": issued,
        "site": site,
        "target_date": target,
        "p_flyable": str(p),
        "n_members": "31",
        "criteria_version": "1",
    }


class MergeTest(unittest.TestCase):
    def test_appends_new_issued_date(self):
        old = [row("2026-10-02", "a", "2026-10-02")]
        new = [row("2026-10-03", "a", "2026-10-03")]
        self.assertEqual(store.merge(old, new, "2026-10-03"), old + new)

    def test_rerun_replaces_same_day_without_duplicates(self):
        prior = row("2026-10-02", "a", "2026-10-02")
        first = [row("2026-10-03", "a", "2026-10-03", 0.1)]
        second = [row("2026-10-03", "a", "2026-10-03", 0.9)]
        merged = store.merge([prior] + first, second, "2026-10-03")
        self.assertEqual(merged, [prior] + second)

    def test_prior_days_untouched(self):
        old = [row("2026-10-01", "a", "2026-10-05"), row("2026-10-02", "a", "2026-10-05")]
        merged = store.merge(old, [row("2026-10-03", "a", "2026-10-05")], "2026-10-03")
        self.assertEqual(merged[:2], old)

    def test_rejects_wrong_issued_date(self):
        with self.assertRaises(ValueError):
            store.merge([], [row("2026-10-02", "a", "2026-10-02")], "2026-10-03")

    def test_rejects_duplicate_keys(self):
        new = [row("2026-10-03", "a", "2026-10-03")] * 2
        with self.assertRaises(ValueError):
            store.merge([], new, "2026-10-03")


class FileTest(unittest.TestCase):
    def test_round_trip_and_month_path(self):
        with tempfile.TemporaryDirectory() as d:
            path = store.month_path(d, "2026-10-03")
            self.assertEqual(path, Path(d) / "forecasts" / "2026-10.csv")
            rows = [row("2026-10-03", "a", "2026-10-03")]
            store.write_rows(path, rows)
            self.assertEqual(store.read_rows(path), rows)
            self.assertTrue(path.read_text().startswith(",".join(store.COLUMNS) + "\n"))
            self.assertEqual(list(path.parent.glob(".tmp-*")), [])

    def test_missing_file_is_empty(self):
        self.assertEqual(store.read_rows(Path("/nonexistent/x.csv")), [])


if __name__ == "__main__":
    unittest.main()
