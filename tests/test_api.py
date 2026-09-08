"""Tests for CHMU API helpers."""

from datetime import datetime
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

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


def _elements_metadata(rows: list[list]) -> dict:
    """Build a meta2 style payload."""
    return {"data": {"data": {"values": rows}}}


def _stations_metadata(rows: list[list]) -> dict:
    """Build a meta1 style payload."""
    return {"data": {"data": {"values": rows}}}


META2_ROWS = [
    ["10M", "0-20000-0-11518", "T", "Teplota", "C", 2.0, "10M"],
    ["10M", "0-20000-0-11518", "H", "Vlhkost", "%", 2.0, "10M"],
    ["1H", "0-20000-0-11518", "P", "Tlak", "hPa", 2.0, "1H"],
    ["10M", "0-203-0-10102001101", "SRA10M", "Srazky", "mm", 1.0, "10M"],
    ["10M", "0-203-0-99999999999", "SCEa", "Snih", "cm", 1.0, "10M"],
]

META1_ROWS = [
    ["0-20000-0-11518", "GH", "Praha-Ruzyne", "14.26", "50.10", 365, "1980-01-01"],
    ["0-203-0-10102001101", "H4", "Obri dul", "15.727", "50.725", 950, "2020-06-22"],
    ["0-203-0-99999999999", "XX", "Jen snih", "15.0", "50.0", 100, "2020-01-01"],
    ["0-20000-0-04030", "ZIS", "Reykjavik", "-21.90", "64.12", 51, "2015-01-01"],
]


def test_get_stations_with_coords_includes_automatic_stations(mock_session):
    """Automatic 0-203 stations are offered next to professional WMO ones."""
    mock_session.get.side_effect = [
        _http_response(200, _elements_metadata(META2_ROWS)),
        _http_response(200, _stations_metadata(META1_ROWS)),
    ]

    stations = api.get_stations_with_coords()

    assert stations == {
        "11518": {
            "name": "Praha-Ruzyne",
            "latitude": 50.10,
            "longitude": 14.26,
            "elements": ["temperature", "humidity"],
        },
        "0-203-0-10102001101": {
            "name": "Obri dul",
            "latitude": 50.725,
            "longitude": 15.727,
            "elements": ["precipitation"],
        },
    }

    # Reykjavik has no 10M elements at all and the snow-only station exposes
    # nothing this integration maps to a sensor, so both are skipped.
    assert "04030" not in stations
    assert "0-203-0-99999999999" not in stations


def test_get_stations_with_coords_retries_previous_day(mock_session):
    """When today's metadata is missing, previous day's file is used."""
    mock_session.get.side_effect = [
        _http_response(404),
        _http_response(200, _elements_metadata(META2_ROWS)),
        _http_response(404),
        _http_response(200, _stations_metadata(META1_ROWS)),
    ]

    stations = api.get_stations_with_coords()

    assert set(stations) == {"11518", "0-203-0-10102001101"}

    urls = [call.args[0] for call in mock_session.get.call_args_list]
    assert urls[0].endswith("meta2-20251221.json")
    assert urls[1].endswith("meta2-20251220.json")
    assert urls[2].endswith("meta1-20251221.json")
    assert urls[3].endswith("meta1-20251220.json")


def test_get_stations_returns_names(mock_session):
    """Simple station listing maps ids to names."""
    mock_session.get.side_effect = [
        _http_response(200, _elements_metadata(META2_ROWS)),
        _http_response(200, _stations_metadata(META1_ROWS)),
    ]

    assert api.get_stations() == {
        "11518": "Praha-Ruzyne",
        "0-203-0-10102001101": "Obri dul",
    }


def test_station_id_wsi_roundtrip():
    """Professional stations keep their short id, others keep the full WSI."""
    assert api.station_id_to_wsi("11518") == "0-20000-0-11518"
    assert api.station_id_to_wsi("0-203-0-10102001101") == "0-203-0-10102001101"
    assert api.wsi_to_station_id("0-20000-0-11518") == "11518"
    assert api.wsi_to_station_id("0-203-0-10102001101") == "0-203-0-10102001101"


def test_fetch_10min_data_uses_full_wsi_for_automatic_station(mock_session):
    """Automatic stations are fetched from their 0-203 data file."""
    client = api.ChmuApi("0-203-0-10102001101", "Obri dul")
    payload = {
        "data": {
            "data": {
                "values": [
                    [
                        "0-203-0-10102001101",
                        "SRA10M",
                        "2025-12-21T10:00:00Z",
                        0.4,
                        "",
                        0.0,
                    ],
                    ["0-203-0-10102001101", "T", "2025-12-21T10:00:00Z", -3.2, "", 0.0],
                ]
            }
        }
    }
    mock_session.get.return_value = _http_response(200, payload)

    data = client._fetch_10min_data(api.datetime.now())

    url = mock_session.get.call_args.args[0]
    assert url.endswith("10m-0-203-0-10102001101-20251221.json")
    assert data["temperature"] == -3.2
    assert data["precipitation"] == 0.4


def test_parse_chmu_data_omits_unmeasured_elements():
    """Elements the station does not report are absent, not None."""
    client = api.ChmuApi("0-203-0-10101014001", "Strazne")
    payload = {
        "data": {
            "data": {
                "values": [
                    [
                        "0-203-0-10101014001",
                        "SRA10M",
                        "2025-12-21T09:50:00Z",
                        0.0,
                        "",
                        0.0,
                    ],
                    [
                        "0-203-0-10101014001",
                        "SRA10M",
                        "2025-12-21T10:00:00Z",
                        1.2,
                        "",
                        0.0,
                    ],
                ]
            }
        }
    }

    data = client._parse_chmu_data(payload)

    assert data["precipitation"] == 1.2
    assert data["timestamp"] == "2025-12-21T10:00:00Z"
    assert "temperature" not in data
    assert "humidity" not in data


def test_parse_chmu_data_ignores_other_stations():
    """Rows belonging to a different WSI are not mixed in."""
    client = api.ChmuApi("11518")
    payload = {
        "data": {
            "data": {
                "values": [
                    ["0-20000-0-11518", "T", "2025-12-21T10:00:00Z", 1.0, "", 0.0],
                    ["0-203-0-11518", "T", "2025-12-21T10:10:00Z", 99.0, "", 0.0],
                ]
            }
        }
    }

    assert client._parse_chmu_data(payload)["temperature"] == 1.0


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
