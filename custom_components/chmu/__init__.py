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

# A download that fails outright is worth retrying long before the next hour is
# up: with no forecast the weather card's Daily tab shows a spinner and offers
# no way to ask again, so a failure at startup leaves it spinning for the whole
# hour. This applies only to a download that did not work - see
# _pace_forecast_polling for why a successful one is never hurried.
FORECAST_RETRY_INTERVAL = timedelta(minutes=5)


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

    # Imported here rather than at module level because it pulls in the
    # recorder, and the test suite imports this package against a small Home
    # Assistant stub from a bare virtualenv.
    from .statistics_import import StatisticsImporter

    statistics_importer = StatisticsImporter(hass, station_id, station_name)

    async def async_update_data():
        """Fetch the station's own measurements.

        A measurement too old to present is reported as such rather than as a
        communication error: the download worked, so calling it one would send
        the next person debugging this at the wrong thing.

        The published file holds an hour of 10 minute rows and only the newest
        becomes the sensor state, so the rest are handed to the recorder as
        hourly statistics on the way past (#18).
        """
        try:
            data = await hass.async_add_executor_job(api.get_current_data)
        except MeasurementUnusable as err:
            raise UpdateFailed(
                f"No usable ČHMÚ measurement for station {station_id}: {err}"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        statistics_importer.async_import(data)
        return data

    def _pace_forecast_polling(retry_soon: bool) -> None:
        """Retry within minutes after a download that failed leaving nothing.

        Only a download that did not work is worth hurrying. Whatever the site
        did return cannot change before the publisher regenerates the file, and
        until it does an unchanged file answers 304 and _fetch replays the very
        same cached bytes - so asking again sooner would re-parse a document
        already known to be unusable, 12 times an hour, for as long as the
        condition lasts. A new run is picked up within the hour either way.
        """
        wanted = FORECAST_RETRY_INTERVAL if retry_soon else FORECAST_SCAN_INTERVAL
        if forecast_coordinator.update_interval != wanted:
            forecast_coordinator.update_interval = wanted

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
            forecast = await hass.async_add_executor_job(forecast_api.get_forecast)
        except ForecastUnusable as err:
            _LOGGER.warning(
                "No usable ČHMÚ forecast for station %s: %s", station_id, err
            )
            # The download worked, so there is nothing a sooner one would find.
            _pace_forecast_polling(False)
            return None
        except Exception as err:
            # A failed fetch leaves the coordinator's existing data in place, so
            # whether this leaves the card empty depends on what is already there.
            _pace_forecast_polling(forecast_coordinator.data is None)
            raise UpdateFailed(
                f"Could not fetch the ČHMÚ forecast for station {station_id}: {err}"
            ) from err

        _pace_forecast_polling(False)
        return forecast

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
