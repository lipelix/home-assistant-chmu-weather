"""Binary sensor for ČHMÚ weather warnings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ChmuConfigEntry
from .warning_entity import ChmuWarningEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChmuConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the warning binary sensor from a config entry."""
    async_add_entities(
        [ChmuWarningBinarySensor(entry.runtime_data.warnings_coordinator, entry)]
    )


class ChmuWarningBinarySensor(ChmuWarningEntity, BinarySensorEntity):
    """On while at least one ČHMÚ warning is in force for the station's ORP.

    Warnings that start later are listed in the attributes (active: false) but
    do not switch it on; the event entity announces them as they are issued.
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_translation_key = "warning"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "warning")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        now = self.now()
        return any(warning.is_active(now) for warning in self.warnings)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.warning_attributes()
