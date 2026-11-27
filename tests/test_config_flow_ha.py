"""The config flow inside a real Home Assistant.

Skips unless pytest-homeassistant-custom-component is installed.
"""

from unittest.mock import patch

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="Home Assistant is not installed",
)

from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
)

from custom_components.chmu.api import StationsUnavailable  # noqa: E402
from custom_components.chmu.const import DOMAIN  # noqa: E402

STATIONS = {
    "11723": {
        "name": "Brno, Tuřany",
        "latitude": 49.1513,
        "longitude": 16.6944,
        "elements": ["temperature", "humidity"],
    },
    "11782": {
        "name": "Mošnov",
        "latitude": 49.691944,
        "longitude": 18.112778,
        "elements": ["temperature"],
    },
    "0-203-0-41501115001": {
        "name": "Tišnov, Hájek",
        "latitude": 49.3489,
        "longitude": 16.4064,
        "elements": ["temperature", "precipitation"],
    },
}


@pytest.fixture(autouse=True)
def enable_custom_integrations(enable_custom_integrations):
    return enable_custom_integrations


@pytest.fixture(autouse=True)
async def home_in_blansko(hass):
    await hass.config.async_update(latitude=49.363, longitude=16.644)


@pytest.fixture(autouse=True)
def no_setup():
    """The created entry is not set up; that is not what these tests check."""
    with patch("custom_components.chmu.async_setup_entry", return_value=True):
        yield


def _stations(*results):
    return patch(
        "custom_components.chmu.config_flow.get_stations_with_coords",
        side_effect=list(results),
    )


async def test_the_nearest_station_is_offered_and_stored(hass):
    with _stations(STATIONS) as lookup:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["description_placeholders"]["nearest_station"] == (
            "Tišnov, Hájek"
        )
        assert result["description_placeholders"]["stations_count"] == "3"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"station_id": "11723"}
        )

    # The submitted station comes from the list the form showed.
    assert lookup.call_count == 1
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Brno, Tuřany (11723)"
    assert result["data"] == {
        "station_id": "11723",
        "station_name": "Brno, Tuřany",
        "station_elements": ["temperature", "humidity"],
        "latitude": 49.1513,
        "longitude": 16.6944,
    }


async def test_an_unreachable_station_list_says_so_and_retries(hass):
    """It used to offer three built-in stations and pick the nearest of them."""
    with _stations(StationsUnavailable("no DNS"), STATIONS):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "unavailable"
        assert result["errors"] == {"base": "cannot_connect"}

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "user"
        assert result["description_placeholders"]["stations_count"] == "3"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"station_id": "11782"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["station_name"] == "Mošnov"


async def test_a_retry_that_fails_again_stays_on_the_error(hass):
    with _stations(StationsUnavailable("no DNS"), StationsUnavailable("no DNS")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["step_id"] == "unavailable"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_a_configured_station_is_not_added_twice(hass):
    MockConfigEntry(domain=DOMAIN, unique_id="11723", data={}).add_to_hass(hass)

    with _stations(STATIONS):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"station_id": "11723"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
