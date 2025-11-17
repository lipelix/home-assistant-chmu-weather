"""Sensor platform for ČHMÚ Weather integration."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfPrecipitationDepth,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATION_ID, CONF_STATION_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ČHMÚ sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    station_id = entry.data[CONF_STATION_ID]
    station_name = entry.data.get(CONF_STATION_NAME, f"Station {station_id}")

    sensors = [
        ChmuTemperatureSensor(coordinator, entry, station_id, station_name),
        ChmuHumiditySensor(coordinator, entry, station_id, station_name),
        ChmuPressureSensor(coordinator, entry, station_id, station_name),
        ChmuPrecipitationSensor(coordinator, entry, station_id, station_name),
        ChmuWindSpeedSensor(coordinator, entry, station_id, station_name),
        ChmuWindDirectionSensor(coordinator, entry, station_id, station_name),
    ]

    async_add_entities(sensors)


class ChmuSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for ČHMÚ sensors."""

    def __init__(self, coordinator, entry, station_id, station_name):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._station_id)},
            "name": self._station_name,
            "manufacturer": "ČHMÚ",
            "model": f"Weather Station {self._station_id}",
            "configuration_url": "https://opendata.chmi.cz",
            "suggested_area": "Outdoors",
        }


class ChmuTemperatureSensor(ChmuSensorBase):
    """Temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_translation_key = "temperature"
    _attr_icon = "mdi:thermometer"

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self._station_id}_temperature"

    @property
    def native_value(self):
        """Return the state."""
        if self.coordinator.data:
            value = self.coordinator.data.get("temperature")
            return value if value not in (None, "", []) else None
        return None


class ChmuHumiditySensor(ChmuSensorBase):
    """Humidity sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = "humidity"
    _attr_icon = "mdi:water-percent"

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self._station_id}_humidity"

    @property
    def native_value(self):
        """Return the state."""
        if self.coordinator.data:
            value = self.coordinator.data.get("humidity")
            return value if value not in (None, "", []) else None
        return None


class ChmuPressureSensor(ChmuSensorBase):
    """Pressure sensor."""

    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPressure.HPA
    _attr_translation_key = "pressure"
    _attr_icon = "mdi:gauge"

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self._station_id}_pressure"

    @property
    def native_value(self):
        """Return the state."""
        if self.coordinator.data:
            value = self.coordinator.data.get("pressure")
            return value if value not in (None, "", []) else None
        return None


class ChmuPrecipitationSensor(ChmuSensorBase):
    """Precipitation sensor."""

    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_translation_key = "precipitation"
    _attr_icon = "mdi:weather-rainy"

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self._station_id}_precipitation"

    @property
    def native_value(self):
        """Return the state."""
        if self.coordinator.data:
            value = self.coordinator.data.get("precipitation")
            return value if value not in (None, "", []) else None
        return None


class ChmuWindSpeedSensor(ChmuSensorBase):
    """Wind speed sensor."""

    _attr_device_class = SensorDeviceClass.WIND_SPEED
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfSpeed.METERS_PER_SECOND
    _attr_translation_key = "wind_speed"
    _attr_icon = "mdi:weather-windy"

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self._station_id}_wind_speed"

    @property
    def native_value(self):
        """Return the state."""
        if self.coordinator.data:
            value = self.coordinator.data.get("wind_speed")
            return value if value not in (None, "", []) else None
        return None


class ChmuWindDirectionSensor(ChmuSensorBase):
    """Wind direction sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°"
    _attr_translation_key = "wind_direction"
    _attr_icon = "mdi:compass"

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self._station_id}_wind_direction"

    @property
    def native_value(self):
        """Return the state."""
        if self.coordinator.data:
            value = self.coordinator.data.get("wind_direction")
            return value if value not in (None, "", []) else None
        return None
