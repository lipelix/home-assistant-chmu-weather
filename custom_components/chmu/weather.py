"""Weather platform for ČHMÚ Weather integration.

Current conditions come from the station's own 10 minute measurements. The
forecast comes from the ALADIN CZ_1km model sampled at that station's
coordinates - see forecast.py for why it is fetched from a static site rather
than from ČHMÚ directly.
"""

import logging

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_STATION_ID, CONF_STATION_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ČHMÚ weather entity from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    station_id = entry.data[CONF_STATION_ID]
    station_name = entry.data.get(CONF_STATION_NAME, f"Station {station_id}")

    async_add_entities(
        [
            ChmuWeather(
                data.coordinator,
                data.forecast_coordinator,
                station_id,
                station_name,
            )
        ]
    )


class ChmuWeather(CoordinatorEntity, WeatherEntity):
    """Measured conditions plus an ALADIN forecast for one ČHMÚ station."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_attribution = "Data provided by ČHMÚ (Czech Hydrometeorological Institute)"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(
        self, coordinator, forecast_coordinator, station_id, station_name
    ) -> None:
        """Initialize the weather entity."""
        super().__init__(coordinator)
        self._forecast_coordinator = forecast_coordinator
        self._station_id = station_id
        self._station_name = station_name
        self._attr_unique_id = f"{station_id}_weather"

    @property
    def device_info(self):
        """Return device information, shared with this station's sensors."""
        return {
            "identifiers": {(DOMAIN, self._station_id)},
            "name": self._station_name,
            "manufacturer": "ČHMÚ",
            "model": f"Weather Station {self._station_id}",
            "configuration_url": "https://opendata.chmi.cz",
            "suggested_area": "Outdoors",
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to forecast updates on top of the measurement updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._forecast_coordinator.async_add_listener(self._handle_forecast_update)
        )

    @callback
    def _handle_forecast_update(self) -> None:
        """Write the new state and push the forecast to its subscribers."""
        self.async_write_ha_state()
        self.hass.async_create_task(self.async_update_listeners(("daily", "hourly")))

    @property
    def _measured(self) -> dict:
        """Return the latest station measurements."""
        return self.coordinator.data or {}

    @property
    def _forecast(self):
        """Return the parsed station forecast, if one was downloaded."""
        return self._forecast_coordinator.data

    @property
    def available(self) -> bool:
        """Return whether either source has something to report.

        The two feeds fail independently: ČHMÚ stops publishing a station's
        10 minute file for a while after local midnight, which must not take
        the forecast down with it - an unavailable entity makes
        weather.get_forecasts raise for anything that calls it.
        """
        return bool(self._measured) or self._forecast is not None

    @property
    def condition(self) -> str | None:
        """Return the current condition.

        The station measures no cloud cover, so the condition comes from the
        forecast hour that covers now.
        """
        forecast = self._forecast
        if forecast is None:
            return None

        current = forecast.current(dt_util.utcnow())
        return current.get("condition") if current else None

    @property
    def native_temperature(self) -> float | None:
        """Return the measured temperature."""
        return self._measured.get("temperature")

    @property
    def humidity(self) -> float | None:
        """Return the measured relative humidity."""
        return self._measured.get("humidity")

    @property
    def native_pressure(self) -> float | None:
        """Return the measured pressure."""
        return self._measured.get("pressure")

    @property
    def native_wind_speed(self) -> float | None:
        """Return the measured wind speed."""
        return self._measured.get("wind_speed")

    @property
    def wind_bearing(self) -> float | None:
        """Return the measured wind bearing."""
        return self._measured.get("wind_direction")

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast."""
        forecast = self._forecast
        return None if forecast is None else _as_forecast(forecast.daily)

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast."""
        forecast = self._forecast
        return None if forecast is None else _as_forecast(forecast.hourly)


def _as_forecast(entries: list[dict]) -> list[Forecast]:
    """Drop the internal bookkeeping keys before handing entries to core."""
    return [
        Forecast(**{key: value for key, value in entry.items() if key[0] != "_"})
        for entry in entries
    ]
