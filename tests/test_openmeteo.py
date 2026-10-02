import unittest
from datetime import date, datetime

from forecast_log import openmeteo
from forecast_log.__main__ import build_rows
from forecast_log.config import Config, Site
from forecast_log.scoring import Criteria

RESPONSE = {
    "timezone": "America/New_York",
    "hourly": {
        "time": ["2026-10-03T10:00", "2026-10-03T11:00"],
        "wind_speed_10m": [10, 11],
        "wind_speed_10m_member01": [12, 13],
        "wind_direction_10m": [270, 271],
        "wind_direction_10m_member01": [272, 273],
        "wind_gusts_10m": [15, 16],
        "wind_gusts_10m_member01": [17, None],
        "precipitation": [0, 0],
        "precipitation_member01": [0, 0.2],
    },
}


class ParseTest(unittest.TestCase):
    def test_control_plus_members(self):
        members = openmeteo.parse_members(RESPONSE)
        self.assertEqual(len(members), 2)
        self.assertEqual(members[0][0].wind_speed, 10)
        self.assertEqual(members[1][1].gust, None)
        self.assertEqual(members[1][1].time, datetime(2026, 10, 3, 11))

    def test_missing_variable_raises(self):
        bad = {"hourly": {**RESPONSE["hourly"]}}
        del bad["hourly"]["precipitation_member01"]
        with self.assertRaises(openmeteo.FetchError):
            openmeteo.parse_members(bad)


class BuildRowsTest(unittest.TestCase):
    def test_fails_whole_run_when_a_day_has_no_data(self):
        crit = Criteria(5, 15, 20, ((225, 315),), 0.1, (10, 12), 1)
        site = Site("s", "S", 40, -83, "America/New_York", crit)
        cfg = Config(1, "gfs_seamless", [site])
        fetch = lambda *_: openmeteo.parse_members(RESPONSE)  # noqa: E731 - only one day of data
        with self.assertRaises(RuntimeError):
            build_rows(cfg, date(2026, 10, 3), fetch=fetch)


if __name__ == "__main__":
    unittest.main()
