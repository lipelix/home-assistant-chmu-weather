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

from .api import ChmuApi
from .const import DOMAIN
from .forecast import ChmuForecastApi, StationForecast

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ČHMÚ Weather from a config entry."""
    station_id = entry.data["station_id"]
    station_name = entry.data.get("station_name", f"Station {station_id}")

    api = ChmuApi(station_id, station_name)
    forecast_api = ChmuForecastApi(station_id)

    async def async_update_data():
        """Fetch data from API."""
        try:
            return await hass.async_add_executor_job(api.get_current_data)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def async_update_forecast():
        """Fetch the per-station forecast.

        A missing forecast must not take the measured sensors down with it, so
        failures are logged and the entity simply reports no forecast.
        """
        try:
            return await hass.async_add_executor_job(forecast_api.get_forecast)
        except Exception:
            _LOGGER.warning(
                "Could not fetch the ČHMÚ forecast for station %s",
                station_id,
                exc_info=True,
            )
            return None

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
    await forecast_coordinator.async_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = ChmuRuntimeData(
        coordinator=coordinator,
        forecast_coordinator=forecast_coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
