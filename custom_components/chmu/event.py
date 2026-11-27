"""Event entity announcing ČHMÚ warnings as they are issued and cancelled."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ChmuConfigEntry
from .alerts import AreaWarnings, changes
from .warning_entity import ChmuWarningEntity

EVENT_ISSUED = "issued"
EVENT_CANCELLED = "cancelled"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChmuConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the warning event entity from a config entry."""
    async_add_entities(
        [ChmuWarningEvent(entry.runtime_data.warnings_coordinator, entry)]
    )


class ChmuWarningEvent(ChmuWarningEntity, EventEntity):
    """Fires when a message brings a new warning or drops one early.

    `issued` comes as soon as ČHMÚ issues the warning, usually hours before it
    takes effect, which is what a "storm tomorrow" notification needs. A
    warning is matched across messages by its code and name (alerts.py,
    WeatherWarning.key): ČHMÚ moves the onset and rewrites the texts with every
    update, and those fire nothing. `cancelled` is a warning that disappeared
    before its end; one that simply ran out is not reported.

    The first message after start-up only sets the baseline, so a restart does
    not announce every warning in force again.
    """

    _attr_event_types = [EVENT_ISSUED, EVENT_CANCELLED]
    _attr_translation_key = "warning_change"
    _attr_icon = "mdi:bell-alert-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "warning_change")
        self._seen: AreaWarnings | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._seen = self.coordinator.data

    @callback
    def _handle_coordinator_update(self) -> None:
        current = self.coordinator.data
        previous, self._seen = self._seen, current
        if (
            previous is None
            or current is None
            or current.identifier == previous.identifier
            and current.orp_code == previous.orp_code
        ):
            super()._handle_coordinator_update()
            return

        now = self.now()
        issued, cancelled = changes(previous.warnings, current.warnings, now)
        for event_type, warnings in (
            (EVENT_ISSUED, issued),
            (EVENT_CANCELLED, cancelled),
        ):
            for warning in warnings:
                data = warning.as_dict(now)
                data["orp"] = current.orp_name
                self._trigger_event(event_type, data)
                # One state per event, or an automation sees only the last.
                self.async_write_ha_state()
        super()._handle_coordinator_update()
