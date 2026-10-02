import tempfile
import unittest
from pathlib import Path

import yaml

from forecast_log import sites

ROOT = Path(__file__).resolve().parent.parent
HEADER = ",".join(sites.CSV_COLUMNS)
ROW = 'ridge,"Ridge, OH",41.5,-81.7,America/New_York,340-20,5,15,18,0.1,10,18,2,,"a note"'


def write(d, name, text):
    p = Path(d) / name
    p.write_text(text, encoding="utf-8")
    return p


class DirRangesTest(unittest.TestCase):
    def test_single_and_multiple(self):
        self.assertEqual(sites.parse_dir_ranges("255-285"), [(255, 285)])
        self.assertEqual(sites.parse_dir_ranges(" 340-20 ; 90-110 "), [(340, 20), (90, 110)])

    def test_bad_input(self):
        for bad in ("", "270", "100-400", "a-b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sites.parse_dir_ranges(bad)


class GenerateTest(unittest.TestCase):
    def gen(self, csv_text, yaml_text=None, lookup=None):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "sites.csv", csv_text)
            y = Path(d) / "sites.yaml"
            if yaml_text is not None:
                y.write_text(yaml_text, encoding="utf-8")
            text, rows = sites.generate(c, y, lookup=lookup, log=lambda m: None)
            return yaml.safe_load(text), rows

    def test_new_file_starts_at_version_1(self):
        out, rows = self.gen(f"{HEADER}\n{ROW}\n")
        self.assertEqual(out["criteria_version"], 1)
        self.assertEqual(out["model"], sites.DEFAULT_MODEL)
        s = out["sites"][0]
        self.assertEqual(s["name"], "Ridge, OH")
        self.assertEqual(s["criteria"]["wind_dir_ranges"], [[340, 20]])
        self.assertIsNone(rows)

    def test_incomplete_and_skipped_rows_not_forecast(self):
        incomplete = 'nodir,No Dir,40,-83,America/New_York,,5,15,18,0.1,10,18,2,,'
        skipped = ROW.replace("ridge,", "held,", 1).replace(',,"a note"', ',yes,"a note"')
        out, _ = self.gen(f"{HEADER}\n{ROW}\n{incomplete}\n{skipped}\n")
        self.assertEqual([s["id"] for s in out["sites"]], ["ridge"])

    def test_skipped_rows_listed_in_yaml_comment(self):
        with tempfile.TemporaryDirectory() as d:
            c = write(d, "sites.csv", f"{HEADER}\n{ROW}\nnodir,N,40,-83,,,,,,,,,,,\n")
            text, _ = sites.generate(c, Path(d) / "s.yaml", log=lambda m: None)
        self.assertIn("#   nodir: missing dir_ranges, speed_min", text)

    def test_incomplete_row_needs_no_timezone_lookup(self):
        def no_lookup(*_):
            raise AssertionError("looked up a skipped row")

        self.gen(f"{HEADER}\n{ROW}\nnodir,N,40,-83,,,,,,,,,,,\n", lookup=no_lookup)

    def test_all_rows_skipped_is_an_error(self):
        with self.assertRaises(ValueError):
            self.gen(f"{HEADER}\nnodir,N,40,-83,,,,,,,,,,,\n")

    def test_row_without_id_is_an_error(self):
        with self.assertRaises(ValueError):
            self.gen(f"{HEADER}\n{ROW}\n{ROW.replace('ridge,', ',', 1)}\n")

    def test_excel_bom_and_blank_rows(self):
        out, _ = self.gen(f"﻿{HEADER}\r\n{ROW}\r\n,,,,,,,,,,,,,,\r\n")
        self.assertEqual(len(out["sites"]), 1)

    def test_version_bumps_only_when_existing_site_changes(self):
        base, _ = self.gen(f"{HEADER}\n{ROW}\n")
        base["criteria_version"] = 3
        base["model"] = "ecmwf_ifs025"
        prev = yaml.safe_dump(base)

        same, _ = self.gen(f"{HEADER}\n{ROW}\n", prev)
        self.assertEqual((same["criteria_version"], same["model"]), (3, "ecmwf_ifs025"))

        added = ROW.replace("ridge,", "other,", 1)
        more, _ = self.gen(f"{HEADER}\n{ROW}\n{added}\n", prev)
        self.assertEqual(more["criteria_version"], 3)

        notes_only, _ = self.gen(f"{HEADER}\n{ROW.replace('a note', 'new note')}\n", prev)
        self.assertEqual(notes_only["criteria_version"], 3)

        for old, new in [(",18,0.1,", ",20,0.1,"), ("340-20", "330-20"),
                         ("America/New_York", "America/Chicago")]:  # fmt: skip
            with self.subTest(change=new):
                changed, _ = self.gen(f"{HEADER}\n{ROW.replace(old, new)}\n", prev)
                self.assertEqual(changed["criteria_version"], 4)

    def test_blank_timezone_is_looked_up(self):
        out, rows = self.gen(
            f"{HEADER}\n{ROW.replace('America/New_York', '')}\n",
            lookup=lambda lat, lon: "America/New_York",
        )
        self.assertEqual(out["sites"][0]["timezone"], "America/New_York")
        self.assertEqual(rows[0]["timezone"], "America/New_York")

    def test_invalid_rows_rejected(self):
        for old, new in [("5,15", "16,15"), ("10,18,2", "10,18,9"), (",,", ",maybe,")]:
            with self.subTest(change=new), self.assertRaises(ValueError):
                self.gen(f"{HEADER}\n{ROW.replace(old, new, 1)}\n")

    def test_missing_column_rejected(self):
        with self.assertRaises(ValueError):
            self.gen("id,name\nx,y\n")


class RepoInSyncTest(unittest.TestCase):
    def test_sites_yaml_matches_sites_csv(self):
        def no_lookup(*_):
            raise AssertionError("sites.csv has a blank timezone; run python -m forecast_log.sites")

        text, _ = sites.generate(ROOT / "sites.csv", ROOT / "sites.yaml", lookup=no_lookup,
                                 log=lambda m: None)  # fmt: skip
        self.assertEqual(
            text,
            (ROOT / "sites.yaml").read_text(encoding="utf-8"),
            "sites.yaml is out of date; run: PYTHONPATH=src python -m forecast_log.sites",
        )


if __name__ == "__main__":
    unittest.main()
