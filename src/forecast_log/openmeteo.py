"""Open-Meteo ensemble API client.

Docs: https://open-meteo.com/en/docs/ensemble-api
Data: CC BY 4.0, Open-Meteo.com. Free tier is non-commercial, no API key.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from .scoring import Hour

ENDPOINT = "https://ensemble-api.open-meteo.com/v1/ensemble"
VARIABLES = ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation")
TIMEOUT_S = 20
RETRIES = 3  # retries after the first attempt
BACKOFF_S = 5  # doubled each retry: 5, 10, 20


class FetchError(Exception):
    pass


def build_url(lat, lon, timezone, model, forecast_days):
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": ",".join(VARIABLES),
        "models": model,
        "forecast_days": forecast_days,
        "timezone": timezone,
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
    }
    return f"{ENDPOINT}?{urllib.parse.urlencode(params)}"


def _get_json(url, sleep=time.sleep):
    last = None
    for attempt in range(RETRIES + 1):
        if attempt:
            sleep(BACKOFF_S * 2 ** (attempt - 1))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "flyorfold-forecast-log"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            # Retry server errors and rate limiting; other 4xx means a bad request.
            if e.code != 429 and e.code < 500:
                body = e.read().decode("utf-8", "replace")[:500]
                raise FetchError(f"HTTP {e.code} for {url}: {body}") from e
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
    raise FetchError(f"giving up after {RETRIES + 1} attempts: {url}: {last}")


def parse_members(data):
    """Turn an ensemble response into a list of per-member Hour lists.

    The control run comes back unsuffixed (e.g. `wind_speed_10m`), and the
    perturbed members as `wind_speed_10m_member01`, `..._member02`, and so on.
    """
    hourly = data["hourly"]
    times = [datetime.fromisoformat(t) for t in hourly["time"]]
    suffixes = [""] + sorted(
        k[len("wind_speed_10m"):] for k in hourly if k.startswith("wind_speed_10m_member")
    )
    members = []
    for sfx in suffixes:
        cols = []
        for var in VARIABLES:
            key = var + sfx
            if key not in hourly:
                raise FetchError(f"response missing {key}")
            cols.append(hourly[key])
        members.append(
            [Hour(t, ws, wd, g, p) for t, ws, wd, g, p in zip(times, *cols, strict=True)]
        )
    return members


def fetch_members(site, model, forecast_days):
    data = _get_json(build_url(site.lat, site.lon, site.timezone, model, forecast_days))
    if data.get("timezone") != site.timezone:
        raise FetchError(f"{site.id}: expected timezone {site.timezone}, got {data.get('timezone')}")
    return parse_members(data)
