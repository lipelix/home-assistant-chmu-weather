"""The warning entities inside a real Home Assistant.

Replays the storm day of 2026-07-17 in Blansko (ORP 6201) from two real
messages (see tests/test_alerts.py):

- 10:55 message: heat stress (yellow) in force 10:53-19:00, storms (yellow)
  from 13:00, plus an outlook.
- 17:09 message: adds very strong storms (orange) 17:07-19:00, and the yellow
  storms now run 19:00-24:00.

Skips unless pytest-homeassistant-custom-component is installed.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="Home Assistant is not installed",
)

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.chmu.alerts import parse_cap  # noqa: E402
from custom_components.chmu.const import DOMAIN  # noqa: E402

CAP = Path(__file__).parent / "fixtures" / "cap"
MORNING = parse_cap((CAP / "storm_2026-07-17_1055.xml").read_bytes())
EVENING = parse_cap((CAP / "storm_2026-07-17_1709.xml").read_bytes())

BLANSKO = {"latitude": 49.363, "longitude": 16.644}
STATION = {
    "station_id": "0-203-0-11723",
    "station_name": "Blansko",
    "station_elements": ["temperature"],
}

BINARY = "binary_sensor.blansko_weather_warning"
LEVEL = "sensor.blansko_warning_level"
EVENT = "event.blansko_warning_change"
ACTIVE = "sensor.blansko_active_warnings"


def local(hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A time on 2026-07-17 in Prague (UTC+2 in summer)."""
    return datetime(2026, 7, 17, hour - 2, minute, second, tzinfo=UTC)


@pytest.fixture(autouse=True)
def enable_custom_integrations(enable_custom_integrations):
    return enable_custom_integrations


@pytest.fixture(autouse=True)
def frozen_clock(freezer):
    freezer.move_to(local(11))
    return freezer


@pytest.fixture(autouse=True)
def station_feeds():
    """Measurements answer, the forecast is simply not there."""
    with (
        patch(
            "custom_components.chmu.api.ChmuApi.get_current_data",
            return_value={"temperature": 30.1, "timestamp": "2026-07-17T09:00:00"},
        ),
        patch(
            "custom_components.chmu.forecast.ChmuForecastApi.get_forecast",
            side_effect=RuntimeError("no forecast in this test"),
        ),
    ):
        yield


@pytest.fixture
def feed():
    """The national message the entries see; set .return_value to change it."""
    with patch(
        "custom_components.chmu.alerts.WarningsFeed.get", return_value=MORNING
    ) as get:
        yield get


async def _setup(hass, data: dict, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Blansko", data=data, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _advance(hass, freezer, when: datetime) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_warnings_in_force_and_upcoming(hass, feed):
    await _setup(hass, {**STATION, **BLANSKO})

    binary = hass.states.get(BINARY)
    assert binary.state == "on"
    warnings = binary.attributes["warnings"]
    assert [(w["level"], w["active"]) for w in warnings] == [
        ("yellow", True),  # heat stress since 10:53
        ("yellow", False),  # storms from 13:00
    ]
    assert binary.attributes["orp"] == "Blansko"
    assert binary.attributes["orp_code"] == "6201"
    assert binary.attributes["outlook"]
    assert hass.states.get(LEVEL).state == "yellow"
    # Home Assistant runs in English here, so the English texts of the message.
    assert hass.states.get(ACTIVE).state == "Moderate Heat Stress"

    # The first message only sets the baseline.
    assert hass.states.get(EVENT).state == STATE_UNKNOWN


async def test_a_new_message_fires_issued(hass, feed, freezer):
    await _setup(hass, {**STATION, **BLANSKO})

    feed.return_value = EVENING
    await _advance(hass, freezer, local(17, 10))

    event = hass.states.get(EVENT)
    assert event.attributes["event_type"] == "issued"
    assert event.attributes["level"] == "orange"
    assert event.attributes["active"] is True
    assert event.attributes["orp"] == "Blansko"
    assert hass.states.get(LEVEL).state == "orange"
    assert (
        hass.states.get(ACTIVE).state
        == "Major Thunderstorm Impact, Moderate Heat Stress"
    )


async def test_a_dropped_warning_fires_cancelled(hass, feed, freezer):
    feed.return_value = EVENING
    freezer.move_to(local(17, 10))
    await _setup(hass, {**STATION, **BLANSKO})
    assert hass.states.get(EVENT).state == STATE_UNKNOWN

    feed.return_value = MORNING
    await _advance(hass, freezer, local(17, 20))

    event = hass.states.get(EVENT)
    assert event.attributes["event_type"] == "cancelled"
    assert event.attributes["level"] == "orange"


async def test_the_state_follows_the_clock_without_a_download(hass, feed, freezer):
    """The orange warning ends at 19:00 whether or not anything is polled."""
    feed.return_value = EVENING
    freezer.move_to(local(17, 10))
    await _setup(hass, {**STATION, **BLANSKO})
    await _advance(hass, freezer, local(18, 59, 59))
    assert hass.states.get(LEVEL).state == "orange"
    downloads = feed.call_count

    await _advance(hass, freezer, local(19, 0, 1))

    assert feed.call_count == downloads
    assert hass.states.get(LEVEL).state == "yellow"
    assert hass.states.get(BINARY).state == "on"
    assert hass.states.get(ACTIVE).state == "Moderate Thunderstorm Impact"

    await _advance(hass, freezer, local(23, 59, 59))
    await _advance(hass, freezer, datetime(2026, 7, 17, 22, 0, 1, tzinfo=UTC))
    assert hass.states.get(LEVEL).state == "none"
    assert hass.states.get(BINARY).state == "off"
    assert hass.states.get(BINARY).attributes["warnings"] == []
    assert hass.states.get(ACTIVE).state == "No warning"


async def test_a_czech_home_assistant_gets_the_czech_names(hass, feed, freezer):
    await hass.config.async_update(language="cs")
    feed.return_value = EVENING
    freezer.move_to(local(17, 10))
    await _setup(hass, {**STATION, **BLANSKO})

    active = hass.states.get("sensor.blansko_platne_vystrahy")
    assert active.state == "Velmi silné bouřky, Silná zátěž teplem"


async def test_an_older_entry_looks_its_coordinates_up_once(hass, feed):
    """Entries from before 1.9.0 stored no coordinates."""
    with patch(
        "custom_components.chmu.get_stations_with_coords",
        return_value={STATION["station_id"]: {"name": "Blansko", **BLANSKO}},
    ) as lookup:
        entry = await _setup(hass, dict(STATION))

    assert lookup.call_count == 1
    assert entry.data["latitude"] == BLANSKO["latitude"]
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(BINARY).attributes["orp_code"] == "6201"


async def test_a_station_outside_czechia_leaves_the_warnings_unavailable(hass, feed):
    await _setup(hass, {**STATION, "latitude": 48.2, "longitude": 16.37})

    assert hass.states.get(BINARY).state == STATE_UNAVAILABLE
    assert hass.states.get(LEVEL).state == STATE_UNAVAILABLE
    # The station's own sensors do not depend on it.
    assert hass.states.get("sensor.blansko_temperature").state == "30.1"


async def test_the_options_choose_another_orp(hass, feed):
    entry = await _setup(hass, {**STATION, **BLANSKO})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["description_placeholders"] == {"station_orp": "Blansko"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"orp": "3209"}
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.options == {"orp": "3209"}
    binary = hass.states.get(BINARY)
    assert binary.attributes["orp"] == "Plzeň"
    # Plzeň had only the storms, from 13:00.
    assert binary.state == "off"
    assert hass.states.get(LEVEL).state == "none"
