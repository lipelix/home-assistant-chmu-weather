"""API client for ČHMÚ Weather."""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from .const import (
    API_BASE_URL,
    API_FORECAST_NOW_URL,
    API_METADATA_PATH,
    API_NOW_PATH,
    ELEMENT_MAP,
    MEASUREMENT_STALE_AFTER,
    MEASUREMENT_UNUSABLE_AFTER,
    METADATA_ELEMENTS_PREFIX,
    METADATA_STATIONS_PREFIX,
    OBS_TYPE_10M,
    USER_AGENT,
    WMO_WSI_PREFIX,
)

_LOGGER = logging.getLogger(__name__)
_CR_TEXT_FORECAST_RE = re.compile(
    r'href="(web_pCRntx_\d{6}\.json)"[^<]*</a>\s+(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})'
)


class NoStationData(Exception):
    """A downloaded file carries no measurement rows for this station.

    Deliberately not a ValueError: requests raises ValueError subclasses for a
    malformed body and for a broken URL, and those must keep propagating. This
    one means the file parsed and simply holds nothing for us, so another day
    is worth trying.
    """


class MeasurementUnusable(Exception):
    """The newest measurement is too old to present as a current reading.

    Same shape as ForecastUnusable in forecast.py: the download worked, the
    answer is just not usable, so it must not be served either.
    """


def _utc_day_candidates() -> tuple[datetime, datetime]:
    """Return the current and previous UTC day, in the order to try them.

    ČHMÚ names every published file after the UTC day. Both the metadata and
    the measurement path need that pair, and they used to derive it
    separately - which is how they came to disagree in the first place (#5).
    """
    now = datetime.now(UTC)
    return now, now - timedelta(days=1)


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a ČHMÚ measurement timestamp into an aware datetime.

    Returns None for anything unparseable rather than failing the poll: an
    unexpected stamp format must not cost the reading itself, it only means
    the age cannot be checked.
    """
    if not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# Fallback used when the station metadata cannot be downloaded.
_FALLBACK_STATIONS = {
    "11450": {
        "name": "Plzeň, Mikulka",
        "latitude": 49.764722,
        "longitude": 13.378889,
        "elements": ["temperature", "humidity", "precipitation", "wind_speed"],
    },
    "11518": {
        "name": "Praha-Ruzyně",
        "latitude": 50.1008,
        "longitude": 14.26,
        "elements": ["temperature", "humidity", "precipitation", "wind_speed"],
    },
    "11782": {
        "name": "Brno-Tuřany",
        "latitude": 49.1513,
        "longitude": 16.6944,
        "elements": ["temperature", "humidity", "precipitation", "wind_speed"],
    },
}


def station_id_to_wsi(station_id: str) -> str:
    """Convert a stored station id to the full WSI used in ČHMÚ file names.

    Professional WMO stations are stored as bare ids ("11450") for backwards
    compatibility, everything else already carries the full WSI.
    """
    if "-" in station_id:
        return station_id
    return f"{WMO_WSI_PREFIX}{station_id}"


def wsi_to_station_id(wsi: str) -> str:
    """Convert a WSI to the station id stored in the config entry."""
    if wsi.startswith(WMO_WSI_PREFIX):
        return wsi[len(WMO_WSI_PREFIX) :]
    return wsi


def new_session() -> requests.Session:
    """Create a requests session with the integration User-Agent.

    Shared with forecast.py so both ČHMÚ and the forecast site see one
    identifiable client.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _fetch_metadata_with_fallback(
    session: requests.Session, log_context: str, prefix: str = METADATA_STATIONS_PREFIX
) -> dict[str, Any]:
    """Fetch today's metadata or fall back to previous day when necessary.

    The file is named after the UTC day and published at about 00:02 UTC, so
    the fallback covers only that couple of minutes - plus a day ČHMÚ skips
    entirely.
    """
    now, previous_day = _utc_day_candidates()
    date_str = now.strftime("%Y%m%d")
    filename = f"{prefix}-{date_str}.json"
    url = f"{API_BASE_URL}{API_METADATA_PATH}/{filename}"

    _LOGGER.info("Fetching %s from: %s", log_context, url)

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as err:
        if err.response.status_code == 404:
            # Try previous day's metadata
            date_str = previous_day.strftime("%Y%m%d")
            filename = f"{prefix}-{date_str}.json"
            url = f"{API_BASE_URL}{API_METADATA_PATH}/{filename}"

            _LOGGER.info(
                "Today's metadata not found, fetching %s from: %s", log_context, url
            )
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        raise


def _metadata_values(metadata: dict[str, Any]) -> list[list[Any]]:
    """Extract the value rows out of a ČHMÚ metadata document."""
    return metadata.get("data", {}).get("data", {}).get("values", [])


def _fetch_station_elements(session: requests.Session) -> dict[str, list[str]]:
    """Return the supported sensor keys per WSI from the element metadata.

    Format of meta2 rows:
    [OBS_TYPE, WSI, EG_EL_ABBREVIATION, NAME, UN_DESCRIPTION, HEIGHT, SCHEDULE]
    Only the 10 minute observation schedule is consumed by this integration.
    """
    metadata = _fetch_metadata_with_fallback(
        session, "station elements", METADATA_ELEMENTS_PREFIX
    )

    elements: dict[str, list[str]] = {}
    for row in _metadata_values(metadata):
        if len(row) < 3:
            continue

        obs_type, wsi, abbreviation = row[0], row[1], row[2]
        if obs_type != OBS_TYPE_10M or not wsi:
            continue

        key = ELEMENT_MAP.get(abbreviation)
        if key is None:
            continue

        station_elements = elements.setdefault(wsi, [])
        if key not in station_elements:
            station_elements.append(key)

    _LOGGER.info("Found 10M elements for %d stations", len(elements))
    return elements


def get_stations() -> dict[str, str]:
    """Fetch available stations from ČHMÚ metadata."""
    return {
        station_id: info["name"]
        for station_id, info in get_stations_with_coords().items()
    }


def get_stations_with_coords() -> dict[str, dict[str, Any]]:
    """Fetch available stations with coordinates from ČHMÚ metadata.

    Includes both professional WMO stations ("0-20000-0-...") and automatic
    stations ("0-203-0-..."). A station is offered only when it publishes at
    least one element this integration can turn into a sensor.

    Returns:
        Dict mapping station ID to station info with name, latitude, longitude
        and the list of supported sensor keys.
    """
    session = new_session()

    try:
        elements_by_wsi = _fetch_station_elements(session)
        metadata = _fetch_metadata_with_fallback(session, "stations with coordinates")

        stations: dict[str, dict[str, Any]] = {}
        values = _metadata_values(metadata)

        _LOGGER.info("Got %d total entries from metadata", len(values))

        for station in values:
            # Format: [WSI, GH_ID, FULL_NAME, GEOGR1, GEOGR2,
            #          ELEVATION, BEGIN_DATE]
            if len(station) < 5:
                continue

            wsi = station[0]
            full_name = station[2]
            longitude = station[3]  # GEOGR1
            latitude = station[4]  # GEOGR2

            if not wsi or not full_name:
                continue

            # Skip stations without coordinates
            if longitude in (None, "") or latitude in (None, ""):
                continue

            # Skip stations that publish nothing we can map to a sensor
            supported = elements_by_wsi.get(wsi)
            if not supported:
                continue

            stations[wsi_to_station_id(wsi)] = {
                "name": full_name,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "elements": supported,
            }

        _LOGGER.info("Found %d stations with coordinates", len(stations))
        return stations
    except Exception:
        _LOGGER.exception("Failed to fetch stations with coordinates")
        # Fallback to a basic set with approximate coordinates
        return {
            station_id: dict(info) for station_id, info in _FALLBACK_STATIONS.items()
        }


class ChmuApi:
    """API client for ČHMÚ weather data."""

    def __init__(self, station_id: str, station_name: str | None = None):
        """Initialize the API client."""
        self.station_id = station_id
        self.wsi = station_id_to_wsi(station_id)
        self.station_name = station_name or f"Station {station_id}"
        self.session = new_session()

    def get_current_data(self) -> dict[str, Any]:
        """Get current weather data from ČHMÚ."""
        data = self._fetch_10min_data_with_fallback()

        # Text forecast is optional; measured station data should still work
        # even when forecast endpoint is unavailable.
        try:
            forecast = self._fetch_latest_cr_text_forecast()
            description = self._extract_weather_description(forecast)
            if description:
                data["weather_description"] = description

            created_at = forecast.get("datumVytvoreni")
            if created_at:
                data["weather_description_timestamp"] = created_at
        except Exception:
            _LOGGER.debug(
                "Could not fetch text weather description from forecast endpoint",
                exc_info=True,
            )

        return data

    def _fetch_10min_data_with_fallback(self) -> dict[str, Any]:
        """Return the latest usable 10 minute measurements for this station.

        ČHMÚ names the data file after the UTC day but does not publish a new
        day's first chunk until about 01:02 UTC, so for the first hour of every
        UTC day only the previous day's file exists. Reading it keeps the
        sensors on the last real measurement instead of dropping to
        unavailable, and stops a restart inside that window from failing setup
        with ConfigEntryNotReady.

        How old the result may be is bounded by _check_freshness, not by which
        file it came from: the fallback is written for a gap of about an hour,
        but a station that stops reporting leaves yesterday's file sitting
        there for a whole day.
        """
        now, previous_day = _utc_day_candidates()

        data = self._fetch_10min_data(now)
        if not data:
            data = self._fetch_10min_data(previous_day)
            if data:
                _LOGGER.info(
                    "ČHMÚ has published no data for station %s on %s yet, "
                    "reading %s instead",
                    self.station_id,
                    now.strftime("%Y-%m-%d"),
                    previous_day.strftime("%Y-%m-%d"),
                )

        if not data:
            raise ValueError(f"No data available for station {self.station_id}")

        self._check_freshness(data, now)
        return data

    def _check_freshness(self, data: dict[str, Any], now: datetime) -> None:
        """Warn about an ageing measurement, refuse an unusable one.

        A sensor state carries no age of its own - Home Assistant stamps it
        with the time it was written - so an unbounded reading would enter long
        term statistics as if it had just been measured.
        """
        measured_at = _parse_timestamp(data.get("timestamp"))
        if measured_at is None:
            return

        age = now - measured_at
        if age > MEASUREMENT_UNUSABLE_AFTER:
            raise MeasurementUnusable(
                f"the newest measurement for station {self.station_id} is from "
                f"{measured_at:%Y-%m-%d %H:%MZ}, "
                f"{age // timedelta(hours=1)} hours old"
            )

        if age > MEASUREMENT_STALE_AFTER:
            _LOGGER.warning(
                "The newest ČHMÚ measurement for station %s is %d hours old "
                "(%s); the station may have stopped reporting",
                self.station_id,
                age // timedelta(hours=1),
                data["timestamp"],
            )

    def _fetch_10min_data(self, date: datetime) -> dict[str, Any] | None:
        """Fetch 10-minute interval data for one UTC date.

        Returns None when ČHMÚ has nothing for that date, so the caller can
        try another day: the file may not be published yet, or it may carry no
        rows for this station. A malformed body or an unexpected document
        shape is not that case and keeps propagating.
        """
        # Format: 10m-{WSI}-{YYYYMMDD}.json, named after the UTC day - the
        # measurement timestamps it holds are UTC as well.
        date_str = date.strftime("%Y%m%d")
        filename = f"10m-{self.wsi}-{date_str}.json"
        url = f"{API_BASE_URL}{API_NOW_PATH}/{filename}"

        _LOGGER.debug("Fetching data from: %s", url)

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return self._parse_chmu_data(response.json())
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                _LOGGER.debug("Data file not found: %s", filename)
                return None
            raise
        except NoStationData as e:
            _LOGGER.debug("Nothing for station %s in %s: %s", self.wsi, filename, e)
            return None

    def _parse_chmu_data(self, json_data: dict[str, Any]) -> dict[str, Any]:
        """Parse CHMU JSON data format.

        Data format:
        Array of [station_id, element, timestamp, value, flag, quality]

        Elements:
        T (temp), H (humidity), P (pressure), SRA10M (precip),
        F (wind speed), D (wind dir)
        """
        # An absent values array means the published format changed, which is
        # a different problem from a day with nothing in it and must not be
        # retried as one.
        document = json_data.get("data")
        payload = document.get("data") if isinstance(document, dict) else None
        if not isinstance(payload, dict) or "values" not in payload:
            raise ValueError(
                "Unexpected ČHMÚ document: no data.data.values array. "
                "The published format may have changed."
            )

        values = payload["values"]
        if not values:
            raise NoStationData("the file carries no measurement rows")

        # Get the most recent values for each element
        latest_values = {}
        for row in values:
            if len(row) < 4:
                continue

            station_id = row[0]
            element = row[1]
            timestamp = row[2]
            value = row[3]

            # Only process our station's data
            if station_id != self.wsi:
                continue

            # Keep only the latest value for each element
            if (
                element not in latest_values
                or timestamp > latest_values[element]["timestamp"]
            ):
                latest_values[element] = {"value": value, "timestamp": timestamp}

        if not latest_values:
            raise NoStationData(f"no rows for station {self.station_id}")

        # Map CHMU elements to our sensor values. Elements the station does not
        # measure are left out entirely instead of being reported as None.
        result: dict[str, Any] = {
            key: latest_values[element]["value"]
            for element, key in ELEMENT_MAP.items()
            if element in latest_values
        }

        result["station_name"] = self.station_name
        result["timestamp"] = self._latest_timestamp(latest_values)

        _LOGGER.debug(f"Parsed data: {result}")
        return result

    @staticmethod
    def _latest_timestamp(latest_values: dict[str, dict[str, Any]]) -> str:
        """Return the newest measurement timestamp, preferring temperature."""
        if "T" in latest_values:
            return latest_values["T"]["timestamp"]

        timestamps = [entry["timestamp"] for entry in latest_values.values()]
        return max(timestamps) if timestamps else datetime.now(UTC).isoformat()

    def _fetch_latest_cr_text_forecast(self) -> dict[str, Any]:
        """Fetch latest Czech Republic text forecast JSON."""
        index_url = f"{API_FORECAST_NOW_URL}/"
        index_response = self.session.get(index_url, timeout=30)
        index_response.raise_for_status()

        latest_filename = self._parse_latest_cr_text_filename(index_response.text)
        if not latest_filename:
            raise ValueError("No web_pCRntx forecast file found in index")

        forecast_url = f"{API_FORECAST_NOW_URL}/{latest_filename}"
        _LOGGER.debug("Fetching forecast text data from: %s", forecast_url)

        forecast_response = self.session.get(forecast_url, timeout=30)
        forecast_response.raise_for_status()
        return forecast_response.json()

    def _parse_latest_cr_text_filename(self, index_html: str) -> str | None:
        """Parse index HTML and return the latest web_pCRntx file."""
        candidates: list[tuple[datetime, str]] = []

        for filename, modified in _CR_TEXT_FORECAST_RE.findall(index_html):
            try:
                modified_time = datetime.strptime(modified, "%d-%b-%Y %H:%M")
            except ValueError:
                continue
            candidates.append((modified_time, filename))

        if not candidates:
            return None

        return max(candidates, key=lambda item: item[0])[1]

    def _extract_weather_description(self, forecast_json: dict[str, Any]) -> str | None:
        """Extract weather description from forecast JSON."""
        features = forecast_json.get("data", {}).get("features", [])
        if not isinstance(features, list):
            return None

        for feature in features:
            properties = feature.get("properties", {})
            entries = properties.get("data", [])
            if not isinstance(entries, list):
                continue

            for entry in entries:
                if entry.get("name") != "textWeather":
                    continue
                display_text = entry.get("displayText")
                if isinstance(display_text, str) and display_text.strip():
                    return " ".join(display_text.replace("\xa0", " ").split())

        return None
