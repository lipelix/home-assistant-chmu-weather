"""The hourly statistics really reach the recorder inside Home Assistant.

The aggregation itself is covered by tests/test_statistics.py without Home
Assistant. What needs a real core is everything around it: that the metadata
is shaped the way the recorder accepts, that the rows survive the import queue,
and that re-offering an hour rewrites it instead of duplicating it.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="Home Assistant is not installed",
)

from homeassistant.components.recorder.statistics import (  # noqa: E402
    statistics_during_period,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402
from pytest_homeassistant_custom_component.components.recorder.common import (  # noqa: E402
    async_wait_recording_done,
)

from custom_components.chmu.const import DOMAIN  # noqa: E402

FIRST_HOUR = datetime(2026, 9, 12, 18, tzinfo=UTC)
SECOND_HOUR = FIRST_HOUR + timedelta(hours=1)

# The batch from issue #18: six rows published at once, of which the sensor
# keeps only 17.0.
TEMPERATURES = [18.1, 17.8, 17.7, 17.1, 16.9, 17.0]


def _history(hour: datetime, values: list[float]) -> list[list]:
    """Build the 10 minute rows of one hour as api.py collects them."""
    return [
        [(hour + timedelta(minutes=10 * index)).isoformat(), value]
        for index, value in enumerate(values)
    ]


def _measured(history: dict) -> dict:
    """Build one poll's data around a history."""
    return {
        "temperature": history["temperature"][-1][1],
        "wind_direction": 225,
        "station_name": "Plzeň, Mikulka",
        "timestamp": history["temperature"][-1][0],
        "history": history,
    }


@pytest.fixture
def no_forecast():
    """Keep the forecast download out of the way of the measurement path."""
    response = MagicMock()
    response.status_code = 500
    response.raise_for_status.side_effect = RuntimeError("no forecast in this test")

    with patch("requests.Session.get", return_value=response):
        yield


async def _setup(hass, data: dict) -> MockConfigEntry:
    """Set up a station whose poll returns the given data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Plzeň, Mikulka",
        data={
            "station_id": "11450",
            "station_name": "Plzeň, Mikulka",
            "station_elements": ["temperature"],
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.chmu.api.ChmuApi.get_current_data", return_value=data
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    return entry


async def _hourly(hass, statistic_id: str) -> list[dict]:
    """Read back every hour stored for one statistic id."""
    await async_wait_recording_done(hass)
    stats = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        FIRST_HOUR - timedelta(hours=1),
        None,
        {statistic_id},
        "hour",
        None,
        {"mean", "min", "max"},
    )
    return stats.get(statistic_id, [])


async def test_a_batch_is_stored_as_one_hour_with_its_real_extremes(
    recorder_mock, enable_custom_integrations, no_forecast, hass
):
    """All six rows describe the hour, not just the newest one."""
    data = _measured({"temperature": _history(FIRST_HOUR, TEMPERATURES)})

    await _setup(hass, data)

    (hour,) = await _hourly(hass, "chmu:11450_temperature")
    assert hour["start"] == FIRST_HOUR.timestamp()
    assert hour["min"] == 16.9
    assert hour["max"] == 18.1
    assert hour["mean"] == pytest.approx(17.433, abs=0.001)


async def test_wind_direction_is_stored_as_a_circular_mean(
    recorder_mock, enable_custom_integrations, no_forecast, hass
):
    """The recorder accepts the circular metadata and keeps the angle."""
    data = _measured(
        {
            "temperature": _history(FIRST_HOUR, TEMPERATURES),
            "wind_direction": _history(FIRST_HOUR, [350.0, 10.0]),
        }
    )

    await _setup(hass, data)

    (hour,) = await _hourly(hass, "chmu:11450_wind_direction")
    assert hour["mean"] == pytest.approx(0.0, abs=0.001) or hour["mean"] == (
        pytest.approx(360.0, abs=0.001)
    )


async def test_an_hour_offered_again_is_rewritten_not_duplicated(
    recorder_mock, enable_custom_integrations, no_forecast, hass
):
    """ČHMÚ serves the same hour for an hour, so every poll re-offers it.

    The second poll is the one that matters: the same hour comes back with all
    six rows where the first poll saw three, and it has to end up stored once,
    complete.
    """
    partial = _measured({"temperature": _history(FIRST_HOUR, TEMPERATURES[:3])})
    entry = await _setup(hass, partial)

    complete = _measured(
        {
            "temperature": _history(FIRST_HOUR, TEMPERATURES)
            + _history(SECOND_HOUR, [12.0, 12.4]),
        }
    )
    with patch(
        "custom_components.chmu.api.ChmuApi.get_current_data", return_value=complete
    ):
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    hours = await _hourly(hass, "chmu:11450_temperature")
    assert [hour["start"] for hour in hours] == [
        FIRST_HOUR.timestamp(),
        SECOND_HOUR.timestamp(),
    ]
    assert hours[0]["min"] == 16.9
    assert hours[0]["max"] == 18.1
    assert hours[1]["mean"] == pytest.approx(12.2, abs=0.001)


async def test_a_poll_without_history_changes_nothing(
    recorder_mock, enable_custom_integrations, no_forecast, hass
):
    """An older published format, or a station with nothing mapped, is fine."""
    await _setup(hass, {"temperature": 17.0, "timestamp": FIRST_HOUR.isoformat()})

    assert await _hourly(hass, "chmu:11450_temperature") == []


async def test_a_statistics_failure_does_not_fail_the_poll(
    recorder_mock, enable_custom_integrations, no_forecast, hass
):
    """The sensors are what the integration is for; statistics are extra."""
    data = _measured({"temperature": _history(FIRST_HOUR, TEMPERATURES)})

    with patch(
        "custom_components.chmu.statistics_import.async_add_external_statistics",
        side_effect=RuntimeError("recorder said no"),
    ):
        entry = await _setup(hass, data)

    assert entry.runtime_data.coordinator.last_update_success
    assert hass.states.get("sensor.plzen_mikulka_temperature").state == "17.0"
