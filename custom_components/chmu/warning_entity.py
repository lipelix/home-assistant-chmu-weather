"""Shared base for the entities built on the ČHMÚ warnings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .alerts import WARNINGS_WEB, AreaWarnings, WeatherWarning, next_change
from .const import CONF_STATION_ID, CONF_STATION_NAME, DOMAIN


def station_device_info(entry: Any) -> DeviceInfo:
    """The station's device, shared with the sensors and the weather entity."""
    station_id = entry.data[CONF_STATION_ID]
    return DeviceInfo(
        identifiers={(DOMAIN, station_id)},
        name=entry.data.get(CONF_STATION_NAME, f"Station {station_id}"),
        manufacturer="ČHMÚ",
        model=f"Weather Station {station_id}",
        configuration_url="https://opendata.chmi.cz",
    )


class ChmuWarningEntity(CoordinatorEntity[DataUpdateCoordinator[AreaWarnings]]):
    """An entity whose state follows the warnings in force.

    A message usually announces warnings that start or end hours later, and the
    next message may be a day away, so the state cannot wait for the next poll
    to change: each entity schedules itself for the next onset or expiry.
    """

    _attr_has_entity_name = True
    _attr_attribution = "Data: ČHMÚ (vystrahy-cr.chmi.cz)"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[AreaWarnings],
        entry: Any,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_STATION_ID]}_{key}"
        self._attr_device_info = station_device_info(entry)
        self._unsub_change: CALLBACK_TYPE | None = None

    @property
    def warnings(self) -> tuple[WeatherWarning, ...]:
        data = self.coordinator.data
        return data.warnings if data is not None else ()

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_next_change()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_next_change()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._schedule_next_change()
        super()._handle_coordinator_update()

    @callback
    def _cancel_next_change(self) -> None:
        if self._unsub_change is not None:
            self._unsub_change()
            self._unsub_change = None

    @callback
    def _schedule_next_change(self) -> None:
        self._cancel_next_change()
        moment = next_change(self.warnings, self.now())
        if moment is not None:
            self._unsub_change = async_track_point_in_utc_time(
                self.hass, self._handle_change, moment
            )

    @callback
    def _handle_change(self, _now: datetime) -> None:
        self._unsub_change = None
        self.async_write_ha_state()
        self._schedule_next_change()

    def warning_attributes(self) -> dict[str, Any]:
        """Every warning that has not expired, plus where they come from."""
        data = self.coordinator.data
        if data is None:
            return {}
        now = self.now()
        return {
            "warnings": [
                warning.as_dict(now)
                for warning in data.warnings
                if not warning.is_expired(now)
            ],
            "outlook": "\n\n".join(
                outlook.description
                for outlook in data.outlooks
                if not outlook.is_expired(now) and outlook.description
            )
            or None,
            "orp": data.orp_name,
            "orp_code": data.orp_code,
            "issued": data.sent.isoformat(),
            "web": WARNINGS_WEB,
        }
