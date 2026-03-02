"""Tests for CHMU API helpers."""

from datetime import datetime
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock
import sys

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Stub classes for Home Assistant imports
class _ConfigEntry:
    """Stub for ConfigEntry."""


class _Platform:
    """Stub for Platform."""

    SENSOR = "sensor"


class _HomeAssistant:
    """Stub for HomeAssistant."""


class _DataUpdateCoordinator:
    """Stub for DataUpdateCoordinator."""


class _UpdateFailed(Exception):
    """Stub for UpdateFailed."""


def _ensure_homeassistant_stub() -> None:
    """Stub Home Assistant modules to allow importing integration code."""
    if "homeassistant" in sys.modules:
        return

    # Create module hierarchy
    for module_path, attrs in [
        ("homeassistant", {}),
        ("homeassistant.config_entries", {"ConfigEntry": _ConfigEntry}),
        ("homeassistant.const", {"Platform": _Platform}),
        ("homeassistant.core", {"HomeAssistant": _HomeAssistant}),
        ("homeassistant.helpers", {}),
        (
            "homeassistant.helpers.update_coordinator",
            {
                "DataUpdateCoordinator": _DataUpdateCoordinator,
                "UpdateFailed": _UpdateFailed,
            },
        ),
    ]:
        mod = ModuleType(module_path)
        for name, value in attrs.items():
            setattr(mod, name, value)
        sys.modules[module_path] = mod


_ensure_homeassistant_stub()
api = import_module("custom_components.chmu.api")


@pytest.fixture(autouse=True)
def freeze_datetime(monkeypatch):
    """Freeze datetime.now() to a known value for deterministic URLs."""

    class FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return cls(2025, 12, 21)

        @classmethod
        def utcnow(cls):
            return cls(2025, 12, 21)

    monkeypatch.setattr(api, "datetime", FixedDatetime)


@pytest.fixture
def mock_session(monkeypatch):
    """Provide a patched requests.Session instance."""
    session = MagicMock()
    session.headers = {}
    monkeypatch.setattr(api.requests, "Session", MagicMock(return_value=session))
    return session


def _http_response(status_code: int, payload: dict | None = None) -> MagicMock:
    """Build a mock HTTP response with optional JSON payload."""
    response = MagicMock()
    response.status_code = status_code

    if status_code >= 400:
        http_error = requests.exceptions.HTTPError(
            "error", response=SimpleNamespace(status_code=status_code)
        )
        response.raise_for_status.side_effect = http_error
    else:
        response.raise_for_status.return_value = None
        response.json.return_value = payload or {}

    return response


def test_get_stations_with_coords_retries_previous_day(mock_session):
    """When today's metadata is missing, previous day's file is used."""
    metadata = {
        "data": {
            "data": {
                "values": [
                    [
                        "0-20000-0-11518",
                        "GH",
                        "Praha-Ruzyne",
                        "14.26",
                        "50.10",
                        365,
                        "1980-01-01",
                    ]
                ]
            }
        }
    }

    mock_session.get.side_effect = [
        _http_response(404),
        _http_response(200, metadata),
    ]

    stations = api.get_stations_with_coords()

    assert stations == {
        "11518": {"name": "Praha-Ruzyne", "latitude": 50.10, "longitude": 14.26}
    }

    assert mock_session.get.call_count == 2
    today_url = mock_session.get.call_args_list[0].args[0]
    yesterday_url = mock_session.get.call_args_list[1].args[0]
    assert today_url.endswith("meta1-20251221.json")
    assert yesterday_url.endswith("meta1-20251220.json")


def test_get_stations_retries_previous_day(mock_session):
    """Station list should also retry with previous day metadata."""
    metadata = {
        "data": {
            "data": {
                "values": [
                    [
                        "0-20000-0-11518",
                        "GH",
                        "Praha-Ruzyne",
                    ]
                ]
            }
        }
    }

    mock_session.get.side_effect = [
        _http_response(404),
        _http_response(200, metadata),
    ]

    stations = api.get_stations()

    assert stations == {"11518": "Praha-Ruzyne"}

    assert mock_session.get.call_count == 2
    today_url = mock_session.get.call_args_list[0].args[0]
    yesterday_url = mock_session.get.call_args_list[1].args[0]
    assert today_url.endswith("meta1-20251221.json")
    assert yesterday_url.endswith("meta1-20251220.json")


def test_parse_latest_cr_text_filename_uses_modified_timestamp():
    """Newest forecast file should be selected by modified time."""
    client = api.ChmuApi("11518")
    index_html = """
    <a href="web_pCRntx_282100.json">web_pCRntx_282100.json</a> 28-Feb-2026 20:52
    <a href="web_pCRntx_010315.json">web_pCRntx_010315.json</a> 01-Mar-2026 03:23
    """

    filename = client._parse_latest_cr_text_filename(index_html)

    assert filename == "web_pCRntx_010315.json"


def test_get_current_data_adds_weather_description(monkeypatch):
    """Text weather description is merged into current sensor payload."""
    client = api.ChmuApi("11518")

    monkeypatch.setattr(
        client,
        "_fetch_10min_data",
        MagicMock(return_value={"temperature": 12, "station_name": "Praha"}),
    )
    monkeypatch.setattr(
        client,
        "_fetch_latest_cr_text_forecast",
        MagicMock(
            return_value={
                "datumVytvoreni": "2026-03-02T03:19:33.067Z",
                "data": {
                    "features": [
                        {
                            "properties": {
                                "data": [
                                    {
                                        "name": "textWeather",
                                        "displayText": "  Jasno\xa0až polojasno.  ",
                                    }
                                ]
                            }
                        }
                    ]
                },
            }
        ),
    )

    data = client.get_current_data()

    assert data["temperature"] == 12
    assert data["weather_description"] == "Jasno až polojasno."
    assert data["weather_description_timestamp"] == "2026-03-02T03:19:33.067Z"
