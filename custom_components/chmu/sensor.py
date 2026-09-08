"""Sensor platform for ČHMÚ Weather integration."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ChmuConfigEntry
from .const import (
    CONF_STATION_ELEMENTS,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChmuConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ČHMÚ sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    station_id = entry.data[CONF_STATION_ID]
    station_name = entry.data.get(CONF_STATION_NAME, f"Station {station_id}")

    # Automatic stations measure only a subset of elements (many report
    # precipitation only). Entries created before this was tracked have no
    # element list, so fall back to creating every sensor.
    supported = entry.data.get(CONF_STATION_ELEMENTS)
    if not supported:
        supported = list(SENSOR_TYPES)

    sensors = [
        sensor_class(coordinator, entry, station_id, station_name)
        for key, sensor_class in SENSOR_TYPES.items()
        if key in supported
    ]

    # The text forecast is issued for the whole country, not per station.
    sensors.append(
        ChmuWeatherDescriptionSensor(coordinator, entry, station_id, station_name)
    )

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


class ChmuWeatherDescriptionSensor(ChmuSensorBase):
    """Weather description sensor from CHMI text forecast."""

    _MAX_STATE_LENGTH = 255
    _attr_translation_key = "weather_description"
    _attr_icon = "mdi:text-box-outline"

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self._station_id}_weather_description"

    @property
    def native_value(self):
        """Return the state."""
        value = self._description_value()
        if value is None:
            return None
        if len(value) <= self._MAX_STATE_LENGTH:
            return value
        return f"{value[: self._MAX_STATE_LENGTH - 3]}..."

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        if not self.coordinator.data:
            return None

        attrs = {}
        description = self._description_value()
        if description and len(description) > self._MAX_STATE_LENGTH:
            attrs["full_text"] = description

        updated_at = self.coordinator.data.get("weather_description_timestamp")
        if updated_at:
            attrs["forecast_updated_at"] = updated_at

        return attrs or None

    def _description_value(self):
        """Return normalized description text or None."""
        if not self.coordinator.data:
            return None
        value = self.coordinator.data.get("weather_description")
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None


SENSOR_TYPES = {
    "temperature": ChmuTemperatureSensor,
    "humidity": ChmuHumiditySensor,
    "pressure": ChmuPressureSensor,
    "precipitation": ChmuPrecipitationSensor,
    "wind_speed": ChmuWindSpeedSensor,
    "wind_direction": ChmuWindDirectionSensor,
}
