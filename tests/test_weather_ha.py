"""End to end check of the weather platform inside a real Home Assistant.

Unlike the other test modules this one needs Home Assistant installed, so it
skips unless pytest-homeassistant-custom-component is available:

    pip install pytest-homeassistant-custom-component
    pytest tests/test_weather_ha.py

It sets the config entry up through Home Assistant itself, so it catches the
things a stub cannot: wrong entity attribute names, unit conversion, and the
forecast subscription contract.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="Home Assistant is not installed",
)

from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
)

from custom_components.chmu.const import DOMAIN  # noqa: E402
from custom_components.chmu.forecast import LOCAL_TIMEZONE  # noqa: E402

# The entity's condition, the local day boundary and the precipitation window
# all depend on the clock, so the clock is pinned. Without this the suite
# passed only during a nine-hour window each day: after local sunset the
# condition is correctly clear-night rather than sunny, from mid-afternoon the
# wet hours cross local midnight into the next day, and after 22:00 UTC the
# first daily row is already yesterday in Prague.
FROZEN_NOW = datetime(2026, 9, 8, 10, 30, tzinfo=UTC)
FROZEN_NIGHT = datetime(2026, 9, 8, 20, 30, tzinfo=UTC)

# ALADIN runs at 00/06/12/18 UTC and the data lands about 75 minutes later, so
# 06Z is the run a 10:30 fetch would really be serving.
RUN = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)

MEASURED = {
    "temperature": 21.3,
    "humidity": 48,
    "pressure": 1017.2,
    "wind_speed": 3.4,
    "wind_direction": 225,
    "precipitation": 0.0,
    "station_name": "Plzeň, Mikulka",
    "timestamp": "2026-09-08T12:00:00",
}


@pytest.fixture(autouse=True)
def enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/chmu."""
    return enable_custom_integrations


@pytest.fixture(autouse=True)
def frozen_clock(freezer):
    """Pin the clock so the forecast assertions are deterministic."""
    freezer.move_to(FROZEN_NOW)
    return freezer


def _published_document(run: datetime) -> dict:
    """Build a forecast document shaped exactly like the published files."""
    hourly = []
    for step in range(-1, 72):
        valid = run + timedelta(hours=step)
        wet = 6 <= step <= 8
        hourly.append(
            {
                "datetime": valid.isoformat().replace("+00:00", "Z"),
                "temperature": 18.0 + step % 5,
                "humidity": 55,
                "cloud_coverage": 90 if wet else 10,
                "wind_speed": 18.0,
                "wind_bearing": 270,
                "precipitation_type": 1 if wet else 0,
                "precipitation": 1.2 if wet else 0.0,
            }
        )

    # Keyed by the local date, the way the publisher does it: the 06Z and 18Z
    # extremes both fall on the same Prague date as their UTC stamp.
    first_day = run.astimezone(LOCAL_TIMEZONE).date()
    daily = [
        {
            "date": (first_day + timedelta(days=day)).isoformat(),
            "temperature": 26.0 - day,
            "templow": 12.0 - day,
        }
        for day in range(3)
    ]

    return {
        "schema": 1,
        "model": "ALADIN CZ_1km",
        "run": run.isoformat().replace("+00:00", "Z"),
        "generated": run.isoformat().replace("+00:00", "Z"),
        "station": {
            "station_id": "0-20000-0-11450",
            "name": "Plzeň, Mikulka",
            "latitude": 49.764722,
            "longitude": 13.378889,
            "elevation": 359.8,
        },
        "hourly": hourly,
        "daily": daily,
    }


@pytest.fixture
def forecast_response():
    """Serve a freshly stamped forecast document to the forecast client."""
    document = _published_document(RUN)

    response = MagicMock()
    response.status_code = 200
    response.headers = {"ETag": 'W/"test"'}
    response.raise_for_status.return_value = None
    response.json.return_value = json.loads(json.dumps(document))

    with patch("requests.Session.get", return_value=response) as session_get:
        yield session_get


@pytest.fixture
def measured_response():
    """Keep the station's own measurements answering for the whole test.

    Scoped to the test rather than to setup, because a test that moves the
    clock triggers the measurement coordinator's own refresh.
    """
    with patch(
        "custom_components.chmu.api.ChmuApi.get_current_data", return_value=MEASURED
    ) as get_current_data:
        yield get_current_data


@pytest.fixture
async def setup_entry(hass, forecast_response, measured_response):
    """Set up a config entry for the Plzeň station."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Plzeň, Mikulka",
        data={
            "station_id": "11450",
            "station_name": "Plzeň, Mikulka",
            "station_elements": ["temperature", "humidity", "wind_speed"],
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


async def test_weather_entity_reports_measured_conditions(hass, setup_entry):
    """The entity state mixes measured values with the forecast condition."""
    state = hass.states.get("weather.plzen_mikulka")

    assert state is not None
    assert state.state == "sunny"
    assert state.attributes["temperature"] == 21.3
    assert state.attributes["humidity"] == 48
    assert state.attributes["pressure"] == 1017.2
    assert state.attributes["wind_bearing"] == 225
    # Measured wind is m/s; Home Assistant presents it in km/h by default.
    assert state.attributes["wind_speed"] == pytest.approx(12.2, abs=0.1)
    assert "ČHMÚ" in state.attributes["attribution"]


async def test_a_clear_sky_after_sunset_is_clear_night(hass, setup_entry, freezer):
    """The condition follows the sun at the station, not just cloud cover."""
    freezer.move_to(FROZEN_NIGHT)
    coordinator = hass.data[DOMAIN][setup_entry.entry_id].forecast_coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Same 10 % cloud cover as the daytime test; only the sun has moved.
    assert hass.states.get("weather.plzen_mikulka").state == "clear-night"


async def test_daily_forecast_is_served(hass, setup_entry):
    """weather.get_forecasts returns the aggregated daily forecast."""
    result = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": "weather.plzen_mikulka", "type": "daily"},
        blocking=True,
        return_response=True,
    )

    forecast = result["weather.plzen_mikulka"]["forecast"]

    assert len(forecast) == 3
    first = forecast[0]
    assert first["temperature"] == 26.0
    assert first["templow"] == 12.0
    assert first["condition"] in ("rainy", "sunny", "partlycloudy", "cloudy")
    assert first["precipitation"] == pytest.approx(3.6, abs=0.1)
    # 18 km/h published, reported in m/s, presented back in km/h.
    assert first["wind_speed"] == pytest.approx(18.0, abs=0.2)


async def test_hourly_forecast_is_served(hass, setup_entry):
    """The hourly forecast keeps the current hour and drops nothing after it."""
    result = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": "weather.plzen_mikulka", "type": "hourly"},
        blocking=True,
        return_response=True,
    )

    forecast = result["weather.plzen_mikulka"]["forecast"]

    # 73 published steps from 05:00Z, minus the five that are already past at
    # the pinned 10:30Z.
    assert len(forecast) == 68
    assert forecast[0]["datetime"].startswith("2026-09-08T10:00:00")
    assert all("datetime" in entry for entry in forecast)
    assert {entry["condition"] for entry in forecast} <= {
        "sunny",
        "clear-night",
        "partlycloudy",
        "cloudy",
        "rainy",
        "pouring",
        "snowy",
        "snowy-rainy",
    }
    # No internal bookkeeping keys leak into the served forecast.
    assert not [key for entry in forecast for key in entry if key.startswith("_")]


async def test_a_new_model_run_updates_the_entity(hass, setup_entry):
    """A forecast refresh reaches both the state and the forecast subscribers."""
    assert hass.states.get("weather.plzen_mikulka").state == "sunny"

    overcast = _published_document(RUN)
    for hour in overcast["hourly"]:
        hour["cloud_coverage"] = 100

    response = MagicMock()
    response.status_code = 200
    response.headers = {"ETag": 'W/"second-run"'}
    response.raise_for_status.return_value = None
    response.json.return_value = overcast

    coordinator = hass.data[DOMAIN][setup_entry.entry_id].forecast_coordinator
    with patch("requests.Session.get", return_value=response):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get("weather.plzen_mikulka").state == "cloudy"


async def test_a_transient_forecast_failure_keeps_the_last_forecast(hass, setup_entry):
    """A failed fetch must not throw away a forecast that is still usable.

    How stale a retained forecast may get is already bounded by
    FORECAST_UNUSABLE_AFTER, so keeping it is strictly better than blanking the
    card until the next hourly poll.
    """
    coordinator = hass.data[DOMAIN][setup_entry.entry_id].forecast_coordinator
    with patch("requests.Session.get", side_effect=OSError("boom")):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    state = hass.states.get("weather.plzen_mikulka")
    result = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": "weather.plzen_mikulka", "type": "daily"},
        blocking=True,
        return_response=True,
    )

    # The coordinator knows it failed, but the data it already had survives.
    assert coordinator.last_update_success is False
    assert coordinator.data is not None
    assert state.state == "sunny"
    assert len(result["weather.plzen_mikulka"]["forecast"]) == 3
    # And the measured side is untouched either way.
    assert state.attributes["temperature"] == 21.3
    assert hass.states.get("sensor.plzen_mikulka_temperature").state == "21.3"


async def test_a_forecast_too_old_to_use_is_dropped(hass, setup_entry):
    """A forecast that arrives but is unusable must not be served."""
    ancient = _published_document(RUN - timedelta(hours=60))

    response = MagicMock()
    response.status_code = 200
    response.headers = {"ETag": 'W/"ancient"'}
    response.raise_for_status.return_value = None
    response.json.return_value = ancient

    coordinator = hass.data[DOMAIN][setup_entry.entry_id].forecast_coordinator
    with patch("requests.Session.get", return_value=response):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    state = hass.states.get("weather.plzen_mikulka")

    # Falling back to an even older forecast would be worse than none.
    assert coordinator.data is None
    assert state.state == "unknown"
    assert state.attributes["temperature"] == 21.3


async def test_a_measurement_outage_leaves_the_forecast_usable(
    hass, setup_entry, measured_response
):
    """The two feeds fail independently.

    ČHMÚ stops publishing a station's 10 minute file for a while after local
    midnight. That used to make the entity unavailable, and an unavailable
    entity makes weather.get_forecasts raise for every automation that calls
    it, even though the forecast itself was fine.
    """
    measured_response.side_effect = ValueError("no data available for station 11450")
    coordinator = hass.data[DOMAIN][setup_entry.entry_id].coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("weather.plzen_mikulka")
    result = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": "weather.plzen_mikulka", "type": "daily"},
        blocking=True,
        return_response=True,
    )

    assert coordinator.last_update_success is False
    assert state.state != "unavailable"
    assert len(result["weather.plzen_mikulka"]["forecast"]) == 3


async def test_sensors_still_work_alongside_the_weather_entity(hass, setup_entry):
    """The measured sensors are unaffected by the added forecast coordinator."""
    state = hass.states.get("sensor.plzen_mikulka_temperature")

    assert state is not None
    assert state.state == "21.3"


async def test_unload_removes_the_entity(hass, setup_entry):
    """Unloading the entry tears the weather entity down."""
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()

    # Home Assistant keeps a restored placeholder around after an unload.
    assert hass.states.get("weather.plzen_mikulka").state == "unavailable"
