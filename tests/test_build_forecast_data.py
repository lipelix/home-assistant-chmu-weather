"""Tests for the forecast builder's download layer.

The builder itself runs in CI against ~63 MB of ČHMÚ GRIB, so only the part
that decides whether to try again is exercised here - which is the part that
decides whether one dropped connection costs a whole model cycle.
"""

import http.client
import sys
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import build_forecast_data as builder  # noqa: E402

URL = "https://opendata.chmi.cz/meteorology/weather/nwp_aladin/CZ_1km/12/"


class _Response:
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Record the backoff instead of waiting it out."""
    slept: list[float] = []
    monkeypatch.setattr(builder.time, "sleep", slept.append)
    return slept


class _Urlopen:
    """A urlopen double that plays out one outcome per call, and counts them.

    A class rather than a closure with an attribute bolted on, so that the
    call log is a declared member and the tests type-check.
    """

    def __init__(self, *outcomes) -> None:
        self._remaining = list(outcomes)
        self.calls: list[str] = []

    def __call__(self, request, timeout=None) -> _Response:
        self.calls.append(request.full_url)
        outcome = self._remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, "boom", Message(), None)


def test_get_retries_a_connect_timeout_and_succeeds(monkeypatch, no_sleeping):
    """The failure that killed run 34350942136 must not fail the run.

    urllib reports a TCP connect timeout as URLError wrapping TimeoutError,
    which is what the traceback in that run showed.
    """
    urlopen = _Urlopen(
        urllib.error.URLError(TimeoutError("timed out")),
        b"<html>listing</html>",
    )
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    assert builder._get(URL, timeout=60) == b"<html>listing</html>"
    assert len(urlopen.calls) == 2
    assert no_sleeping == [5.0]


def test_get_backs_off_between_attempts(monkeypatch, no_sleeping):
    """Waits longer each time, and gives up rather than looping forever."""
    urlopen = _Urlopen(
        *[urllib.error.URLError(TimeoutError("timed out"))] * builder.RETRY_ATTEMPTS
    )
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    with pytest.raises(urllib.error.URLError):
        builder._get(URL, timeout=60)

    assert len(urlopen.calls) == builder.RETRY_ATTEMPTS
    assert no_sleeping == [5.0, 10.0, 15.0]


def test_get_retries_a_body_that_stops_midway(monkeypatch, no_sleeping):
    """A truncated 7 MB download is not an OSError, and still deserves a retry."""
    urlopen = _Urlopen(
        http.client.IncompleteRead(b"half a grib", 5_000_000),
        b"a whole grib",
    )
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    assert builder._get(URL) == b"a whole grib"
    assert len(urlopen.calls) == 2


def test_get_retries_a_reset_connection(monkeypatch, no_sleeping):
    """A bare socket error reaches _get too, not only the URLError wrapper."""
    urlopen = _Urlopen(ConnectionResetError("reset by peer"), b"listing")
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    assert builder._get(URL) == b"listing"
    assert len(urlopen.calls) == 2


def test_get_retries_a_server_error(monkeypatch, no_sleeping):
    """502 from the CDN is transient; the run should ride it out."""
    urlopen = _Urlopen(_http_error(502), b"listing")
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    assert builder._get(URL) == b"listing"
    assert len(urlopen.calls) == 2


def test_get_retries_a_rate_limit(monkeypatch, no_sleeping):
    """429 is the one 4xx that means "later", so it is the one 4xx we retry."""
    urlopen = _Urlopen(_http_error(429), b"listing")
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    assert builder._get(URL) == b"listing"
    assert len(urlopen.calls) == 2


def test_get_does_not_retry_a_missing_file(monkeypatch, no_sleeping):
    """404 must come straight back.

    load_stations asks for today's metadata first and falls back to yesterday's
    on OSError. Retrying the 404 would only delay that fallback, and metadata
    for the current UTC day is legitimately absent for the first minutes of it.
    """
    urlopen = _Urlopen(_http_error(404), b"never reached")
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    with pytest.raises(urllib.error.HTTPError) as raised:
        builder._get(URL, timeout=60)

    assert raised.value.code == 404
    assert len(urlopen.calls) == 1
    assert no_sleeping == []


def test_load_stations_still_falls_back_to_yesterday(monkeypatch, no_sleeping):
    """The 404 fallback survives the retry loop being added under it."""
    day_asked: list[str] = []

    def urlopen(request, timeout=None):
        day_asked.append(request.full_url)
        if len(day_asked) == 1:
            raise _http_error(404)
        return _Response(
            b'{"data": {"data": {"values": ['
            b'["0-20000-0-11518", 1, "Praha", 14.4, 50.1, 300]]}}}'
        )

    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    stations = builder.load_stations()

    assert [s["station_id"] for s in stations] == ["0-20000-0-11518"]
    assert len(day_asked) == 2, "today's file was retried instead of falling back"
    assert no_sleeping == []
