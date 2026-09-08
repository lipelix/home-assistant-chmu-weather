"""Per-station forecast client for ČHMÚ Weather.

The forecast is not downloaded from ČHMÚ directly. ČHMÚ publishes forecasts
either as national prose or as ~70 MB of GRIB per model run, neither of which
an integration can consume. A GitHub Actions job samples the ALADIN CZ_1km
model at every station coordinate and publishes a few kilobytes per station as
a static site; this module reads that.

Deliberately free of Home Assistant imports so the mapping, the day/night
maths and the staleness rules can be tested without a Home Assistant install.
See tools/build_forecast_data.py for the producing side.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .api import station_id_to_wsi
from .const import (
    FORECAST_BASE_URL,
    FORECAST_SCHEMA_VERSION,
    FORECAST_STALE_AFTER,
    FORECAST_UNUSABLE_AFTER,
)

_LOGGER = logging.getLogger(__name__)

# Forecasts are grouped into days as a Czech user reads them, not in UTC.
LOCAL_TIMEZONE = ZoneInfo("Europe/Prague")

# Home Assistant condition strings. Spelled out rather than imported from
# homeassistant.components.weather to keep this module import-free.
CONDITION_CLEAR_NIGHT = "clear-night"
CONDITION_CLOUDY = "cloudy"
CONDITION_PARTLYCLOUDY = "partlycloudy"
CONDITION_POURING = "pouring"
CONDITION_RAINY = "rainy"
CONDITION_SNOWY = "snowy"
CONDITION_SNOWY_RAINY = "snowy-rainy"
CONDITION_SUNNY = "sunny"

# Cloud cover in percent below which the sky counts as clear / broken.
CLOUD_CLEAR_BELOW = 25
CLOUD_BROKEN_BELOW = 75

# Precipitation in mm/h. ALADIN emits small non-zero amounts constantly, so a
# threshold is needed before calling an hour wet; 4 mm/h is heavy rain.
PRECIPITATION_WET_FROM = 0.1
PRECIPITATION_POURING_FROM = 4.0

# Air temperature in °C at which precipitation turns to sleet and to snow.
# ALADIN does publish a precipitation type field, but ČHMÚ documents no code
# table for it, so it is used only as a yes/no wetness hint and the species is
# decided by temperature. Guessing at an undocumented code table would mean
# silently reporting snow in July.
TEMPERATURE_SNOW_BELOW = 0.5
TEMPERATURE_SLEET_BELOW = 2.0

# Solar elevation in degrees at sunset, including refraction and solar radius.
SUNSET_ELEVATION = -0.833

# The daily condition is decided from daylight hours only; an overcast night
# should not make an otherwise sunny day cloudy.
DAYTIME_START_HOUR = 6
DAYTIME_END_HOUR = 20

_HOURLY_KEYS = {
    "temperature": "native_temperature",
    "humidity": "humidity",
    "cloud_coverage": "cloud_coverage",
    "wind_bearing": "wind_bearing",
}


def solar_elevation(when: datetime, latitude: float, longitude: float) -> float:
    """Return the solar elevation in degrees at a time and place.

    Low precision NOAA algorithm, good to about a minute around sunrise, which
    is far tighter than an hourly forecast needs.
    """
    days = when.timestamp() / 86400.0 + 2440587.5 - 2451545.0

    mean_longitude = math.radians((280.460 + 0.9856474 * days) % 360)
    mean_anomaly = math.radians((357.528 + 0.9856003 * days) % 360)
    ecliptic_longitude = mean_longitude + math.radians(
        1.915 * math.sin(mean_anomaly) + 0.020 * math.sin(2 * mean_anomaly)
    )
    obliquity = math.radians(23.439 - 0.0000004 * days)

    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_longitude))
    right_ascension = math.atan2(
        math.cos(obliquity) * math.sin(ecliptic_longitude),
        math.cos(ecliptic_longitude),
    )

    sidereal_time = (18.697374558 + 24.06570982441908 * days) % 24
    hour_angle = math.radians(
        sidereal_time * 15 + longitude - math.degrees(right_ascension)
    )

    latitude_rad = math.radians(latitude)
    return math.degrees(
        math.asin(
            math.sin(latitude_rad) * math.sin(declination)
            + math.cos(latitude_rad) * math.cos(declination) * math.cos(hour_angle)
        )
    )


def is_night(when: datetime, latitude: float, longitude: float) -> bool:
    """Return whether the sun is below the horizon at a time and place."""
    return solar_elevation(when, latitude, longitude) < SUNSET_ELEVATION


def condition(
    *,
    cloud_coverage: float | None,
    precipitation: float | None,
    precipitation_type: int | None,
    temperature: float | None,
    night: bool = False,
) -> str | None:
    """Map one forecast hour to a Home Assistant condition."""
    amount = precipitation or 0.0
    # The type field catches drizzle that rounds to 0.0 mm in the amount.
    wet = amount >= PRECIPITATION_WET_FROM or bool(precipitation_type)

    if wet:
        if temperature is not None:
            if temperature < TEMPERATURE_SNOW_BELOW:
                return CONDITION_SNOWY
            if temperature < TEMPERATURE_SLEET_BELOW:
                return CONDITION_SNOWY_RAINY
        if amount >= PRECIPITATION_POURING_FROM:
            return CONDITION_POURING
        return CONDITION_RAINY

    if cloud_coverage is None:
        return None
    if cloud_coverage < CLOUD_CLEAR_BELOW:
        return CONDITION_CLEAR_NIGHT if night else CONDITION_SUNNY
    if cloud_coverage < CLOUD_BROKEN_BELOW:
        return CONDITION_PARTLYCLOUDY
    return CONDITION_CLOUDY


class ForecastUnusable(Exception):
    """The published forecast is too old to be worth showing.

    Distinct from a fetch failure: the download worked, the answer is just not
    usable, so the previous forecast must not be kept either.
    """


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values)) if values else None


@dataclass
class StationForecast:
    """One station's forecast, already mapped to Home Assistant keys."""

    station_name: str
    latitude: float
    longitude: float
    run: datetime
    generated: datetime | None = None
    hourly: list[dict[str, Any]] = field(default_factory=list)
    daily: list[dict[str, Any]] = field(default_factory=list)

    def age(self, now: datetime) -> timedelta:
        """Return how long ago the model run this forecast came from started."""
        return now - self.run

    def publication_age(self, now: datetime) -> timedelta:
        """Return how long ago this forecast was published.

        Distinct from age(): the builder serves the newest model run that is
        complete, so a freshly published file can carry a run several hours old.
        """
        return now - (self.generated or self.run)

    def is_stale(self, now: datetime) -> bool:
        """Return whether the publishing job looks like it has stopped."""
        return self.publication_age(now) > FORECAST_STALE_AFTER

    def is_unusable(self, now: datetime) -> bool:
        """Return whether the model run behind this forecast is too old."""
        return self.age(now) > FORECAST_UNUSABLE_AFTER

    def current(self, now: datetime) -> dict[str, Any] | None:
        """Return the forecast hour covering ``now``, if there is one."""
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        for entry in self.hourly:
            if entry["_valid_time"] >= current_hour:
                return entry
        return None


def _parse_time(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, accepting the trailing Z form."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _hourly_entries(
    document: dict[str, Any], latitude: float, longitude: float, now: datetime
) -> list[dict[str, Any]]:
    """Map the published hourly rows to Home Assistant forecast entries."""
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    rows = document.get("hourly") or []

    # The publisher stamps each precipitation amount with the END of the hour it
    # accumulated over, because it is the difference between two cumulative
    # model fields. Home Assistant reads an hourly entry the other way round -
    # the amount falls in the hour that STARTS at the entry's timestamp - so the
    # value belonging to an entry is the one published for the following hour.
    # The type shifts with the amount: in the published data a non-zero type
    # appears exactly on the hours with a non-zero difference, so it describes
    # the same accumulation interval rather than an instant.
    precipitation_by_time = {
        _parse_time(row["datetime"]): (
            row["precipitation"],
            row.get("precipitation_type"),
        )
        for row in rows
        if row.get("precipitation") is not None
    }

    entries = []
    for row in rows:
        valid_time = _parse_time(row["datetime"])
        # Keep the hour that is currently running; drop everything before it.
        if valid_time < current_hour:
            continue

        precipitation, precipitation_type = precipitation_by_time.get(
            valid_time + timedelta(hours=1), (None, None)
        )

        entry: dict[str, Any] = {
            "_valid_time": valid_time,
            "datetime": valid_time.isoformat(),
            "condition": condition(
                cloud_coverage=row.get("cloud_coverage"),
                precipitation=precipitation,
                precipitation_type=precipitation_type,
                temperature=row.get("temperature"),
                night=is_night(valid_time, latitude, longitude),
            ),
        }
        for source_key, target_key in _HOURLY_KEYS.items():
            if (value := row.get(source_key)) is not None:
                entry[target_key] = value
        if precipitation is not None:
            entry["native_precipitation"] = precipitation
        if (wind_speed := row.get("wind_speed")) is not None:
            # Published in km/h; the integration reports wind in m/s so that
            # forecast and measured wind share one unit.
            entry["native_wind_speed"] = round(wind_speed / 3.6, 1)
        entries.append(entry)
    return entries


def _daily_entries(
    document: dict[str, Any], hourly: list[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """Combine the published 12 hour extremes with aggregated hourly rows."""
    by_date: dict[str, list[dict[str, Any]]] = {}
    for entry in hourly:
        local_date = entry["_valid_time"].astimezone(LOCAL_TIMEZONE).date()
        by_date.setdefault(local_date.isoformat(), []).append(entry)

    today = now.astimezone(LOCAL_TIMEZONE).date().isoformat()

    entries = []
    for row in document.get("daily") or []:
        date = row["date"]
        if date < today:
            continue

        # The extremes are 12 hour fields, so the last day a run reaches often
        # has the overnight low but not the following afternoon's high. A tile
        # with no high renders as an empty temperature in Home Assistant, and
        # the hours behind it cover only part of the day, so drop the day
        # instead of publishing a half one.
        high = row.get("temperature")
        if high is None:
            continue

        hours = by_date.get(date, [])
        midnight = datetime.fromisoformat(date).replace(tzinfo=LOCAL_TIMEZONE)
        entry: dict[str, Any] = {
            "datetime": midnight.isoformat(),
            "native_temperature": high,
        }

        if (low := row.get("templow")) is not None:
            entry["native_templow"] = low

        precipitation = [
            hour["native_precipitation"]
            for hour in hours
            if "native_precipitation" in hour
        ]
        if precipitation:
            entry["native_precipitation"] = round(sum(precipitation), 1)

        winds = [hour for hour in hours if "native_wind_speed" in hour]
        if winds:
            windiest = max(winds, key=lambda hour: hour["native_wind_speed"])
            entry["native_wind_speed"] = windiest["native_wind_speed"]
            if "wind_bearing" in windiest:
                entry["wind_bearing"] = windiest["wind_bearing"]

        humidity = _mean([h["humidity"] for h in hours if "humidity" in h])
        if humidity is not None:
            entry["humidity"] = humidity

        daytime = [
            hour
            for hour in hours
            if DAYTIME_START_HOUR
            <= hour["_valid_time"].astimezone(LOCAL_TIMEZONE).hour
            < DAYTIME_END_HOUR
        ]
        cloud = _mean(
            [h["cloud_coverage"] for h in daytime or hours if "cloud_coverage" in h]
        )
        if cloud is not None:
            entry["cloud_coverage"] = cloud

        # Cloud cover is judged on daylight hours, precipitation on the whole
        # day: rain that falls at 03:00 still makes it a rainy day.
        entry["condition"] = _daily_condition(hours, cloud, high)
        entries.append(entry)

    return entries


def _daily_condition(
    hours: list[dict[str, Any]], cloud: float | None, high: float | None
) -> str | None:
    """Pick the condition that best describes a whole day.

    Precipitation wins over cloud cover: a day with one wet hour is reported as
    rainy, because that is the part a user needs to plan around.
    """
    wet = [hour for hour in hours if "native_precipitation" in hour]
    total = sum(hour["native_precipitation"] for hour in wet)
    wettest = max(wet, key=lambda hour: hour["native_precipitation"], default=None)

    if wettest is not None and (
        wettest["native_precipitation"] >= PRECIPITATION_WET_FROM
        or total >= PRECIPITATION_WET_FROM
    ):
        return condition(
            cloud_coverage=cloud,
            precipitation=max(wettest["native_precipitation"], PRECIPITATION_WET_FROM),
            precipitation_type=None,
            temperature=wettest.get("native_temperature", high),
        )

    return condition(
        cloud_coverage=cloud,
        precipitation=None,
        precipitation_type=None,
        temperature=high,
    )


def parse_forecast(document: dict[str, Any], now: datetime) -> StationForecast:
    """Turn a published station document into a StationForecast."""
    schema = document.get("schema")
    if schema != FORECAST_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported forecast schema {schema}, expected {FORECAST_SCHEMA_VERSION}"
        )

    station = document["station"]
    latitude = float(station["latitude"])
    longitude = float(station["longitude"])

    hourly = _hourly_entries(document, latitude, longitude, now)
    return StationForecast(
        station_name=station.get("name", ""),
        latitude=latitude,
        longitude=longitude,
        run=_parse_time(document["run"]),
        generated=(
            _parse_time(document["generated"]) if document.get("generated") else None
        ),
        hourly=hourly,
        daily=_daily_entries(document, hourly, now),
    )


class ChmuForecastApi:
    """Downloads one station's forecast from the published static site."""

    def __init__(self, station_id: str, session: requests.Session | None = None):
        """Initialize the forecast client."""
        self.station_id = station_id
        self.wsi = station_id_to_wsi(station_id)
        self.url = f"{FORECAST_BASE_URL}/{self.wsi}.json"
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": "Home-Assistant-CHMU-Integration/1.0"}
        )
        self._etag: str | None = None
        self._document: dict[str, Any] | None = None

    def _fetch(self) -> dict[str, Any]:
        """Return the published document, revalidating the cached copy.

        The site is on a CDN with weak ETags, so an unchanged forecast answers
        304 with no body, which is what keeps this affordable to host.
        """
        headers = {"If-None-Match": self._etag} if self._etag else {}
        response = self.session.get(self.url, headers=headers, timeout=30)

        if response.status_code == 304:
            if self._document is not None:
                _LOGGER.debug("Forecast for %s unchanged (304)", self.wsi)
                return self._document
            # 304 without a cached copy to serve: the body is empty, so parsing
            # it would fail on nothing useful. Drop the validator and ask again.
            _LOGGER.debug("Got 304 for %s with nothing cached, refetching", self.wsi)
            self._etag = None
            response = self.session.get(self.url, timeout=30)

        response.raise_for_status()
        document = response.json()
        self._document = document
        self._etag = response.headers.get("ETag")
        return document

    def get_forecast(self) -> StationForecast:
        """Return the station forecast, revalidating the cached copy.

        The site is on a CDN with weak ETags, so an unchanged forecast costs a
        304 with no body. That is what keeps this affordable to host.
        """
        document = self._fetch()

        now = datetime.now(UTC)
        forecast = parse_forecast(document, now)

        if forecast.is_unusable(now):
            raise ForecastUnusable(
                f"forecast for {self.wsi} is from {forecast.run:%Y-%m-%d %HZ}, "
                f"{forecast.age(now) // timedelta(hours=1)} hours old"
            )

        if forecast.is_stale(now):
            _LOGGER.warning(
                "ČHMÚ forecast for %s was last published %d hours ago; the "
                "publishing job may have stopped",
                self.wsi,
                forecast.publication_age(now) // timedelta(hours=1),
            )

        return forecast
