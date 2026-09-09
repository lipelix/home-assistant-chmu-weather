"""ČHMÚ Weather Integration."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import ChmuApi, MeasurementUnusable
from .forecast import ChmuForecastApi, ForecastUnusable, StationForecast

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.WEATHER]
SCAN_INTERVAL = timedelta(minutes=10)

# ALADIN publishes a new run every 6 hours. Polling hourly costs nothing worth
# counting because an unchanged forecast answers with a 304 and no body, and it
# keeps the lag after a new run short.
FORECAST_SCAN_INTERVAL = timedelta(hours=1)


@dataclass
class ChmuRuntimeData:
    """Coordinators shared by this station's platforms."""

    coordinator: DataUpdateCoordinator
    forecast_coordinator: DataUpdateCoordinator[StationForecast | None]


# Config entry carrying the runtime data above, so the platforms get the
# coordinators typed instead of looking them up in hass.data.
ChmuConfigEntry = ConfigEntry[ChmuRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: ChmuConfigEntry) -> bool:
    """Set up ČHMÚ Weather from a config entry."""
    station_id = entry.data["station_id"]
    station_name = entry.data.get("station_name", f"Station {station_id}")

    api = ChmuApi(station_id, station_name)
    forecast_api = ChmuForecastApi(station_id)

    async def async_update_data():
        """Fetch the station's own measurements.

        A measurement too old to present is reported as such rather than as a
        communication error: the download worked, so calling it one would send
        the next person debugging this at the wrong thing.
        """
        try:
            return await hass.async_add_executor_job(api.get_current_data)
        except MeasurementUnusable as err:
            raise UpdateFailed(
                f"No usable ČHMÚ measurement for station {station_id}: {err}"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def async_update_forecast():
        """Fetch the per-station forecast.

        The two failure kinds are deliberately handled differently. A fetch that
        did not work raises UpdateFailed, which keeps the last forecast on the
        coordinator - a few hours old is far better than none, and how old it may
        get is already bounded by FORECAST_UNUSABLE_AFTER. A forecast that
        arrived but is too old returns None, because there is no point falling
        back to an even older one.

        Either way the measured sensors are on their own coordinator and are
        unaffected.
        """
        try:
            return await hass.async_add_executor_job(forecast_api.get_forecast)
        except ForecastUnusable as err:
            _LOGGER.warning(
                "No usable ČHMÚ forecast for station %s: %s", station_id, err
            )
            return None
        except Exception as err:
            raise UpdateFailed(
                f"Could not fetch the ČHMÚ forecast for station {station_id}: {err}"
            ) from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"ČHMÚ {station_id}",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )
    forecast_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"ČHMÚ forecast {station_id}",
        update_method=async_update_forecast,
        update_interval=FORECAST_SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = ChmuRuntimeData(
        coordinator=coordinator,
        forecast_coordinator=forecast_coordinator,
    )

    # The forecast is fetched from a static site over the public internet and
    # is not needed for the entity to exist, so the first download runs in the
    # background: a slow or unreachable CDN must not hold up startup. Tied to
    # the entry so unloading cancels it.
    entry.async_create_background_task(
        hass,
        forecast_coordinator.async_refresh(),
        name=f"chmu initial forecast {station_id}",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ChmuConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
