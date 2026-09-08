"""Constants for ČHMÚ Weather integration."""

from datetime import timedelta

DOMAIN = "chmu"

CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_STATION_ELEMENTS = "station_elements"

# API endpoints
API_BASE_URL = "https://opendata.chmi.cz/meteorology/climate"
API_NOW_PATH = "/now/data"
API_METADATA_PATH = "/now/metadata"
API_FORECAST_NOW_URL = "https://opendata.chmi.cz/meteorology/weather/forecast/now"

# Per-station forecast, published by .github/workflows/forecast-data.yml. ČHMÚ
# itself offers only a national forecast or ~70 MB of GRIB per model run, so a
# GitHub Actions job samples ALADIN CZ_1km per station and hosts the result.
FORECAST_BASE_URL = "https://lipelix.github.io/home-assistant-chmu-weather/v1"
FORECAST_SCHEMA_VERSION = 1

# ALADIN runs every 6 hours. Well past that means the publishing job stopped;
# scheduled GitHub workflows are disabled after 60 days of repository silence.
FORECAST_STALE_AFTER = timedelta(hours=12)
FORECAST_UNUSABLE_AFTER = timedelta(hours=48)

# Station metadata files (meta1 = stations, meta2 = measured elements per station)
METADATA_STATIONS_PREFIX = "meta1"
METADATA_ELEMENTS_PREFIX = "meta2"

# WSI prefix used by professional WMO stations. Their config entries store only
# the trailing WMO id ("11450") for backwards compatibility; all other stations
# (automatic/climatological, "0-203-0-...") store the full WSI.
WMO_WSI_PREFIX = "0-20000-0-"

# Observation schedule we consume (10 minute interval data).
OBS_TYPE_10M = "10M"

# ČHMÚ element abbreviation -> value key exposed by the API client / sensors.
ELEMENT_MAP = {
    "T": "temperature",
    "H": "humidity",
    "P": "pressure",
    "SRA10M": "precipitation",
    "F": "wind_speed",
    "D": "wind_direction",
}
