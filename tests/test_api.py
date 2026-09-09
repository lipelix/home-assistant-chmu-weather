"""Tests for CHMU API helpers."""

from datetime import UTC, datetime
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

api = import_module("custom_components.chmu.api")


def _freeze(monkeypatch, utc_now: datetime, local_now: datetime | None = None):
    """Patch api.datetime so now(UTC) and a naive now() can disagree.

    They are allowed to differ on purpose: ČHMÚ names its files after the UTC
    day, while the local day on a Prague host rolls over one or two hours
    earlier. Reading the local day is the bug behind issue #5, so the tests
    have to be able to tell the two apart.
    """
    naive = local_now if local_now is not None else utc_now.replace(tzinfo=None)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # Converted rather than returned as-is, so that asking for a
            # non-UTC zone yields that zone's wall clock. Returning the UTC
            # instant for every tz would make the double blind to the aware
            # form of #5 - naming the file after the Prague day.
            return utc_now.astimezone(tz) if tz is not None else naive

    monkeypatch.setattr(api, "datetime", FixedDatetime)


@pytest.fixture(autouse=True)
def freeze_datetime(monkeypatch):
    """Freeze the clock to a known instant for deterministic URLs."""
    _freeze(monkeypatch, datetime(2025, 12, 21, 12, 0, tzinfo=UTC))


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

    data = client._fetch_10min_data(api.datetime.now(UTC))

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


def _10min_payload(wsi: str, timestamp: str, temperature: float) -> dict:
    """Build a 10m data payload holding one temperature row."""
    return {"data": {"data": {"values": [[wsi, "T", timestamp, temperature, "", 0.0]]}}}


def test_fetch_10min_data_falls_back_to_previous_utc_day(mock_session, monkeypatch):
    """Just after UTC midnight only the previous day's file exists (#5)."""
    _freeze(monkeypatch, datetime(2025, 12, 21, 0, 30, tzinfo=UTC))
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    mock_session.get.side_effect = [
        _http_response(404),
        _http_response(
            200,
            _10min_payload("0-20000-0-11518", "2025-12-20T23:50:00Z", -1.5),
        ),
    ]

    data = client._fetch_10min_data_with_fallback()

    assert data["temperature"] == -1.5
    assert data["timestamp"] == "2025-12-20T23:50:00Z"

    urls = [call.args[0] for call in mock_session.get.call_args_list]
    assert urls[0].endswith("10m-0-20000-0-11518-20251221.json")
    assert urls[1].endswith("10m-0-20000-0-11518-20251220.json")


def test_fetch_10min_data_names_the_file_after_the_utc_day(mock_session, monkeypatch):
    """A Prague host is already on the next local day at 00:30 CET (#5).

    The file must still be the UTC one, which exists and holds current data,
    not the local-dated one, which ČHMÚ has not published yet.
    """
    _freeze(
        monkeypatch,
        datetime(2025, 12, 21, 23, 30, tzinfo=UTC),
        local_now=datetime(2025, 12, 22, 0, 30),
    )
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    mock_session.get.return_value = _http_response(
        200, _10min_payload("0-20000-0-11518", "2025-12-21T23:20:00Z", 0.5)
    )

    data = client._fetch_10min_data_with_fallback()

    assert data["temperature"] == 0.5
    assert mock_session.get.call_count == 1
    url = mock_session.get.call_args.args[0]
    assert url.endswith("10m-0-20000-0-11518-20251221.json")


def test_fetch_10min_data_falls_back_when_file_has_no_station_rows(
    mock_session, monkeypatch
):
    """A published file carrying nothing for this station is not usable."""
    _freeze(monkeypatch, datetime(2025, 12, 21, 0, 30, tzinfo=UTC))
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    mock_session.get.side_effect = [
        _http_response(
            200, _10min_payload("0-20000-0-11782", "2025-12-21T00:20:00Z", 9.9)
        ),
        _http_response(
            200, _10min_payload("0-20000-0-11518", "2025-12-20T23:50:00Z", -1.5)
        ),
    ]

    assert client._fetch_10min_data_with_fallback()["temperature"] == -1.5
    assert mock_session.get.call_count == 2


def test_fetch_10min_data_raises_when_neither_day_is_available(mock_session):
    """Both days missing is a real failure and must surface as one."""
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    mock_session.get.side_effect = [_http_response(404), _http_response(404)]

    with pytest.raises(ValueError, match="No data available for station 11518"):
        client._fetch_10min_data_with_fallback()

    # Without this the test also passes against the pre-fix code, which raised
    # the identical message after a single request.
    assert mock_session.get.call_count == 2


def test_fetch_10min_data_propagates_server_errors(mock_session):
    """A 500 is not a missing day, so it is not retried as one."""
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    mock_session.get.side_effect = [_http_response(500), _http_response(404)]

    with pytest.raises(requests.exceptions.HTTPError):
        client._fetch_10min_data_with_fallback()

    assert mock_session.get.call_count == 1


def test_metadata_is_fetched_for_the_utc_day(mock_session, monkeypatch):
    """Metadata file names follow the UTC day too."""
    _freeze(
        monkeypatch,
        datetime(2025, 12, 21, 23, 30, tzinfo=UTC),
        local_now=datetime(2025, 12, 22, 0, 30),
    )
    mock_session.get.side_effect = [
        _http_response(200, _elements_metadata(META2_ROWS)),
        _http_response(200, _stations_metadata(META1_ROWS)),
    ]

    api.get_stations_with_coords()

    urls = [call.args[0] for call in mock_session.get.call_args_list]
    assert urls[0].endswith("meta2-20251221.json")
    assert urls[1].endswith("meta1-20251221.json")


def test_fetch_10min_data_propagates_a_malformed_body(mock_session):
    """A truncated body or an HTML error page must not read as a quiet day.

    requests raises JSONDecodeError, which is a ValueError subclass, so it
    would be swallowed by a broad except and served as yesterday's data.
    """
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    broken = _http_response(200)
    broken.json.side_effect = requests.exceptions.JSONDecodeError("boom", "", 0)
    mock_session.get.side_effect = [broken, _http_response(200)]

    with pytest.raises(requests.exceptions.JSONDecodeError):
        client._fetch_10min_data_with_fallback()

    # The previous day was never reached: this is a failure, not an absence.
    assert mock_session.get.call_count == 1


def test_fetch_10min_data_propagates_an_unexpected_document_shape(mock_session):
    """A renamed field is a format change and must be reported as one.

    Retrying it as a missing day would report a structural break as an absence
    of data, which is the worst possible hint for whoever has to debug it from
    a user's log excerpt.
    """
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    renamed = {"data": {"data": {"rows": [["0-20000-0-11518", "T", "x", 1.0]]}}}
    mock_session.get.return_value = _http_response(200, renamed)

    with pytest.raises(ValueError, match="no data.data.values array"):
        client._fetch_10min_data_with_fallback()

    assert mock_session.get.call_count == 1


def test_fetch_10min_data_refuses_a_measurement_past_the_bound(
    mock_session, monkeypatch
):
    """A station quiet since yesterday must not be served as current.

    The fallback covers a gap of about an hour. A station that stops reporting
    leaves yesterday's file in place all day, and serving its last row would
    feed a day old value into long term statistics stamped as fresh.
    """
    _freeze(monkeypatch, datetime(2025, 12, 21, 12, 0, tzinfo=UTC))
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    mock_session.get.side_effect = [
        _http_response(404),
        _http_response(
            200, _10min_payload("0-20000-0-11518", "2025-12-20T23:50:00Z", -1.5)
        ),
    ]

    with pytest.raises(api.MeasurementUnusable, match="12 hours old"):
        client._fetch_10min_data_with_fallback()


def test_fetch_10min_data_warns_about_an_ageing_measurement(
    mock_session, monkeypatch, caplog
):
    """Between the two thresholds the reading is served, but not silently."""
    _freeze(monkeypatch, datetime(2025, 12, 21, 3, 0, tzinfo=UTC))
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    mock_session.get.return_value = _http_response(
        200, _10min_payload("0-20000-0-11518", "2025-12-20T23:50:00Z", -1.5)
    )

    with caplog.at_level("WARNING"):
        data = client._fetch_10min_data_with_fallback()

    assert data["temperature"] == -1.5
    assert "3 hours old" in caplog.text


def test_fetch_10min_data_serves_the_nightly_gap_without_a_warning(
    mock_session, monkeypatch, caplog
):
    """The case the fallback exists for is normal operation, not a problem."""
    _freeze(monkeypatch, datetime(2025, 12, 21, 0, 30, tzinfo=UTC))
    client = api.ChmuApi("11518", "Praha-Ruzyne")
    mock_session.get.side_effect = [
        _http_response(404),
        _http_response(
            200, _10min_payload("0-20000-0-11518", "2025-12-20T23:50:00Z", -1.5)
        ),
    ]

    with caplog.at_level("WARNING"):
        assert client._fetch_10min_data_with_fallback()["temperature"] == -1.5

    assert caplog.text == ""
