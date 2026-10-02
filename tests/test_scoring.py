import unittest
from datetime import date, datetime, timedelta

from forecast_log.scoring import Criteria, Hour, direction_ok, member_flyable, score_day

DAY = date(2026, 10, 4)
C = Criteria(
    wind_speed_min=5,
    wind_speed_max=15,
    gust_max=20,
    wind_dir_ranges=((225, 315),),
    precip_max=0.1,
    flying_hours=(10, 18),
    min_consecutive_hours=2,
)
GOOD = dict(wind_speed=10, wind_dir=270, gust=15, precip=0)
BAD = dict(wind_speed=25, wind_dir=270, gust=30, precip=0)


def member(day=DAY, overrides=None, default=BAD):
    """24 hours for `day`; `overrides` maps hour -> dict of field values."""
    overrides = overrides or {}
    start = datetime(day.year, day.month, day.day)
    return [
        Hour(start + timedelta(hours=h), **{**default, **overrides.get(h, {})}) for h in range(24)
    ]


class DirectionTest(unittest.TestCase):
    def test_simple_range(self):
        self.assertTrue(direction_ok(270, [(225, 315)]))
        self.assertTrue(direction_ok(225, [(225, 315)]))
        self.assertFalse(direction_ok(200, [(225, 315)]))

    def test_wrapping_range(self):
        r = [(315, 45)]
        self.assertTrue(direction_ok(350, r))
        self.assertTrue(direction_ok(0, r))
        self.assertTrue(direction_ok(360, r))
        self.assertTrue(direction_ok(30, r))
        self.assertFalse(direction_ok(90, r))
        self.assertFalse(direction_ok(300, r))

    def test_multiple_ranges(self):
        r = [(0, 20), (180, 200)]
        self.assertTrue(direction_ok(190, r))
        self.assertFalse(direction_ok(100, r))


class MemberTest(unittest.TestCase):
    def window(self, m):
        return [h for h in m if 10 <= h.time.hour < 18]

    def test_needs_consecutive_hours(self):
        m = member(overrides={11: GOOD, 13: GOOD})  # two good hours, not adjacent
        self.assertFalse(member_flyable(self.window(m), C))
        m = member(overrides={12: GOOD, 13: GOOD})
        self.assertTrue(member_flyable(self.window(m), C))

    def test_good_hours_outside_window_ignored(self):
        m = member(overrides={8: GOOD, 9: GOOD, 18: GOOD, 19: GOOD})
        self.assertFalse(member_flyable(self.window(m), C))

    def test_each_criterion_disqualifies(self):
        for field, value in [
            ("wind_speed", 4),
            ("wind_speed", 16),
            ("gust", 21),
            ("wind_dir", 90),
            ("precip", 0.5),
        ]:
            with self.subTest(field=field, value=value):
                m = member(default={**GOOD, field: value})
                self.assertFalse(member_flyable(self.window(m), C))

    def test_bounds_inclusive(self):
        m = member(default={**GOOD, "wind_speed": 15, "gust": 20, "precip": 0.1})
        self.assertTrue(member_flyable(self.window(m), C))


class ScoreDayTest(unittest.TestCase):
    def test_fraction_of_members(self):
        members = [member(default=GOOD)] * 3 + [member(default=BAD)]
        self.assertEqual(score_day(members, DAY, C), (0.75, 4))

    def test_rounds_to_three_decimals(self):
        members = [member(default=GOOD)] + [member(default=BAD)] * 2
        self.assertEqual(score_day(members, DAY, C), (0.333, 3))

    def test_member_with_missing_data_excluded(self):
        incomplete = member(default=GOOD, overrides={14: {"gust": None}})
        members = [member(default=GOOD), member(default=BAD), incomplete]
        self.assertEqual(score_day(members, DAY, C), (0.5, 2))

    def test_only_scores_requested_day(self):
        next_day = DAY + timedelta(days=1)
        members = [member(default=BAD) + member(day=next_day, default=GOOD)]
        self.assertEqual(score_day(members, DAY, C), (0.0, 1))
        self.assertEqual(score_day(members, next_day, C), (1.0, 1))

    def test_no_data_raises(self):
        members = [member(day=DAY + timedelta(days=1), default=GOOD)]
        with self.assertRaises(ValueError):
            score_day(members, DAY, C)


if __name__ == "__main__":
    unittest.main()
