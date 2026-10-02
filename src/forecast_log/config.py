"""Load and validate sites.yaml."""

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import yaml

from .scoring import Criteria


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    lat: float
    lon: float
    timezone: str
    criteria: Criteria


@dataclass(frozen=True)
class Config:
    criteria_version: int
    model: str
    sites: list


def parse_criteria(raw: dict, site_id: str) -> Criteria:
    try:
        c = Criteria(
            wind_speed_min=float(raw["wind_speed_min"]),
            wind_speed_max=float(raw["wind_speed_max"]),
            gust_max=float(raw["gust_max"]),
            wind_dir_ranges=tuple((float(lo), float(hi)) for lo, hi in raw["wind_dir_ranges"]),
            precip_max=float(raw["precip_max"]),
            flying_hours=(int(raw["flying_hours"][0]), int(raw["flying_hours"][1])),
            min_consecutive_hours=int(raw["min_consecutive_hours"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"site {site_id}: bad or missing criteria field: {e}") from e
    start, end = c.flying_hours
    if not 0 <= start < end <= 24:
        raise ValueError(f"site {site_id}: flying_hours must satisfy 0 <= start < end <= 24")
    if not 1 <= c.min_consecutive_hours <= end - start:
        raise ValueError(f"site {site_id}: min_consecutive_hours must fit in the flying window")
    if c.wind_speed_min > c.wind_speed_max:
        raise ValueError(f"site {site_id}: wind_speed_min > wind_speed_max")
    if not c.wind_dir_ranges:
        raise ValueError(f"site {site_id}: wind_dir_ranges is empty")
    return c


def load(path) -> Config:
    with open(path, encoding="utf-8") as f:
        return parse(yaml.safe_load(f))


def parse(raw: dict) -> Config:
    version = raw.get("criteria_version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("criteria_version must be a positive integer")
    model = raw.get("model")
    if not model:
        raise ValueError("model is required")
    sites = []
    seen = set()
    for s in raw.get("sites") or []:
        sid = s["id"]
        if sid in seen:
            raise ValueError(f"duplicate site id: {sid}")
        seen.add(sid)
        ZoneInfo(s["timezone"])  # raises if unknown
        sites.append(
            Site(
                id=sid,
                name=s.get("name", sid),
                lat=float(s["lat"]),
                lon=float(s["lon"]),
                timezone=s["timezone"],
                criteria=parse_criteria(s["criteria"], sid),
            )
        )
    if not sites:
        raise ValueError("no sites defined")
    return Config(criteria_version=version, model=model, sites=sites)
