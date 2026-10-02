"""Pure scoring logic: ensemble members + site criteria -> p_flyable.

No I/O here. Everything takes plain data so it can be unit tested.
"""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Criteria:
    wind_speed_min: float
    wind_speed_max: float
    gust_max: float
    wind_dir_ranges: tuple  # tuple of (min_deg, max_deg); may wrap through 0
    precip_max: float
    flying_hours: tuple  # (start_hour, end_hour), end exclusive, site-local
    min_consecutive_hours: int


@dataclass(frozen=True)
class Hour:
    """One hourly forecast value set for one ensemble member. Any field may be None."""

    time: datetime  # naive, site-local
    wind_speed: float | None
    wind_dir: float | None
    gust: float | None
    precip: float | None


def direction_ok(deg: float, ranges) -> bool:
    deg = deg % 360
    for lo, hi in ranges:
        lo, hi = lo % 360, hi % 360
        if lo <= hi:
            if lo <= deg <= hi:
                return True
        elif deg >= lo or deg <= hi:  # wraps through north
            return True
    return False


def hour_ok(h: Hour, c: Criteria) -> bool:
    if None in (h.wind_speed, h.wind_dir, h.gust, h.precip):
        return False
    return (
        c.wind_speed_min <= h.wind_speed <= c.wind_speed_max
        and h.gust <= c.gust_max
        and h.precip <= c.precip_max
        and direction_ok(h.wind_dir, c.wind_dir_ranges)
    )


def window_hours(hours, day: date, c: Criteria):
    """Hours of one member that fall on `day` inside the flying window, in time order."""
    start, end = c.flying_hours
    return sorted(
        (h for h in hours if h.time.date() == day and start <= h.time.hour < end),
        key=lambda h: h.time,
    )


def member_flyable(window, c: Criteria) -> bool:
    run = 0
    prev = None
    for h in window:
        consecutive = prev is not None and (h.time - prev).total_seconds() == 3600
        if hour_ok(h, c):
            run = run + 1 if consecutive else 1
            if run >= c.min_consecutive_hours:
                return True
        else:
            run = 0
        prev = h.time
    return False


def member_complete(window, c: Criteria) -> bool:
    """True if the member has every hour of the window with no missing values."""
    start, end = c.flying_hours
    if len(window) != end - start:
        return False
    return all(None not in (h.wind_speed, h.wind_dir, h.gust, h.precip) for h in window)


def score_day(members, day: date, c: Criteria):
    """Return (p_flyable, n_members) for one site/day.

    `members` is a list of per-member hour lists. Members with any missing
    data in the flying window are left out of both the numerator and n_members.
    Raises ValueError if no member has complete data for the day.
    """
    usable = 0
    flyable = 0
    for hours in members:
        window = window_hours(hours, day, c)
        if not member_complete(window, c):
            continue
        usable += 1
        if member_flyable(window, c):
            flyable += 1
    if usable == 0:
        raise ValueError(f"no ensemble member has complete data for {day}")
    return round(flyable / usable, 3), usable
