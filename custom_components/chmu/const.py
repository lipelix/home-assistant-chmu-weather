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

# The two thresholds measure different things on purpose.
#
# STALE is about the publishing job and is measured from when the data was
# published, not from the model reference time. The job runs every 6 hours, but
# GitHub delays scheduled workflows - drifts of about 4 hours have been
# observed - and the builder deliberately falls back to the previous model run
# when the newest one is incomplete. Measuring from the run time therefore
# warns about a job that is working fine. 18 hours is three missed slots even
# allowing for that drift.
#
# UNUSABLE is about the content and stays keyed on the model run: a forecast
# from a 48 hour old run has lost its value however recently it was published.
FORECAST_STALE_AFTER = timedelta(hours=18)
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
