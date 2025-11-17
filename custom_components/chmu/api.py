"""API client for ČHMÚ Weather."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import requests

from .const import API_BASE_URL, API_METADATA_PATH, API_NOW_PATH

_LOGGER = logging.getLogger(__name__)


def get_stations() -> Dict[str, str]:
    """Fetch available stations from ČHMÚ metadata."""
    session = requests.Session()
    session.headers.update({"User-Agent": "Home-Assistant-CHMU-Integration/1.0"})

    # Try today's metadata first
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"meta1-{date_str}.json"
    url = f"{API_BASE_URL}{API_METADATA_PATH}/{filename}"

    _LOGGER.info(f"Fetching stations from: {url}")

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        metadata = response.json()

        stations = {}
        values = metadata.get("data", {}).get("data", {}).get("values", [])

        _LOGGER.info(f"Got {len(values)} total entries from metadata")

        for station in values:
            if len(station) < 3:
                continue

            wsi = station[0]  # e.g., "0-20000-0-11450"
            full_name = station[2]  # e.g., "Plzeň, Mikulka"

            # Only include professional stations (0-20000-0-11*)
            if not wsi or not wsi.startswith("0-20000-0-11"):
                continue

            # Extract WMO_ID from WSI (last part after last dash)
            if full_name:
                wmo_id = wsi.split("-")[-1]
                stations[wmo_id] = full_name

        _LOGGER.info(f"Found {len(stations)} stations")
        return stations
    except Exception as e:
        _LOGGER.exception(f"Failed to fetch stations: {e}")
        # Fallback to a basic set
        return {
            "11450": "Plzeň, Mikulka",
            "11518": "Praha-Ruzyně",
            "11782": "Brno-Tuřany",
        }


def get_stations_with_coords() -> Dict[str, Dict[str, Any]]:
    """Fetch available stations with coordinates from ČHMÚ metadata.

    Returns:
        Dict mapping station ID to station info with name, latitude, longitude.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": "Home-Assistant-CHMU-Integration/1.0"})

    # Try today's metadata first
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"meta1-{date_str}.json"
    url = f"{API_BASE_URL}{API_METADATA_PATH}/{filename}"

    _LOGGER.info(f"Fetching stations with coordinates from: {url}")

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        metadata = response.json()

        stations = {}
        values = metadata.get("data", {}).get("data", {}).get("values", [])

        _LOGGER.info(f"Got {len(values)} total entries from metadata")

        for station in values:
            # Format: [WSI, GH_ID, FULL_NAME, GEOGR1, GEOGR2,
            #          ELEVATION, BEGIN_DATE]
            if len(station) < 5:
                continue

            wsi = station[0]  # e.g., "0-20000-0-11450"
            full_name = station[2]  # e.g., "Plzeň, Mikulka"
            longitude = station[3]  # GEOGR1
            latitude = station[4]  # GEOGR2

            # Only include professional stations (0-20000-0-11*)
            if not wsi or not wsi.startswith("0-20000-0-11"):
                continue

            # Skip stations without coordinates
            if not longitude or not latitude:
                continue

            # Extract WMO_ID from WSI (last part after last dash)
            if full_name:
                wmo_id = wsi.split("-")[-1]
                stations[wmo_id] = {
                    "name": full_name,
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                }

        _LOGGER.info(f"Found {len(stations)} stations with coordinates")
        return stations
    except Exception as e:
        _LOGGER.exception(f"Failed to fetch stations with coordinates: {e}")
        # Fallback to a basic set with approximate coordinates
        return {
            "11450": {
                "name": "Plzeň, Mikulka",
                "latitude": 49.764722,
                "longitude": 13.378889,
            },
            "11518": {
                "name": "Praha-Ruzyně",
                "latitude": 50.1008,
                "longitude": 14.26,
            },
            "11782": {
                "name": "Brno-Tuřany",
                "latitude": 49.1513,
                "longitude": 16.6944,
            },
        }


class ChmuApi:
    """API client for ČHMÚ weather data."""

    def __init__(self, station_id: str, station_name: Optional[str] = None):
        """Initialize the API client."""
        self.station_id = station_id
        self.station_name = station_name or f"Station {station_id}"
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Home-Assistant-CHMU-Integration/1.0"}
        )

    def get_current_data(self) -> Dict[str, Any]:
        """Get current weather data from ČHMÚ."""
        now = datetime.now()

        data = self._fetch_10min_data(now)
        if not data:
            raise ValueError(f"No data available for station {self.station_id}")
        return data

    def _fetch_10min_data(self, date: datetime) -> Optional[Dict[str, Any]]:
        """Fetch 10-minute interval data for a specific date."""
        # Format: 10m-0-20000-0-{station_id}-{YYYYMMDD}.json
        date_str = date.strftime("%Y%m%d")
        filename = f"10m-0-20000-0-{self.station_id}-{date_str}.json"
        url = f"{API_BASE_URL}{API_NOW_PATH}/{filename}"

        _LOGGER.debug(f"Fetching data from: {url}")

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            json_data = response.json()
            return self._parse_chmu_data(json_data)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                _LOGGER.debug(f"Data file not found: {filename}")
                return None
            raise

    def _parse_chmu_data(self, json_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse CHMU JSON data format.

        Data format:
        Array of [station_id, element, timestamp, value, flag, quality]

        Elements:
        T (temp), H (humidity), P (pressure), SRA10M (precip),
        F (wind speed), D (wind dir)
        """
        values = json_data.get("data", {}).get("data", {}).get("values", [])

        if not values:
            raise ValueError("No data values found in response")

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
            if not station_id.endswith(self.station_id):
                continue

            # Keep only the latest value for each element
            if (
                element not in latest_values
                or timestamp > latest_values[element]["timestamp"]
            ):
                latest_values[element] = {"value": value, "timestamp": timestamp}

        if not latest_values:
            raise ValueError(f"No data found for station {self.station_id}")

        # Map CHMU elements to our sensor values
        timestamp = latest_values.get("T", {}).get(
            "timestamp", datetime.now().isoformat()
        )

        result = {
            "temperature": latest_values.get("T", {}).get("value"),
            "humidity": latest_values.get("H", {}).get("value"),
            "pressure": latest_values.get("P", {}).get("value"),
            "precipitation": latest_values.get("SRA10M", {}).get("value", 0),
            "wind_speed": latest_values.get("F", {}).get("value"),
            "wind_direction": latest_values.get("D", {}).get("value"),
            "station_name": self.station_name,
            "timestamp": timestamp,
        }

        _LOGGER.debug(f"Parsed data: {result}")
        return result
