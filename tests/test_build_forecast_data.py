"""Tests for the forecast builder's download layer.

The builder itself runs in CI against ~63 MB of ČHMÚ GRIB, so only the part
that decides whether to try again is exercised here - which is the part that
decides whether one dropped connection costs a whole model cycle.
"""

import http.client
import sys
import time
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import build_forecast_data as builder  # noqa: E402

URL = "https://opendata.chmi.cz/meteorology/weather/nwp_aladin/CZ_1km/12/"


class _OnRead:
    """Marks an outcome that fails while the body is read, not on connect.

    The distinction is the whole point of one of these tests: a truncated
    download surfaces from response.read(), so an implementation that only
    guards the urlopen call has to be seen to fail.
    """

    def __init__(self, error: Exception) -> None:
        self.error = error


class _Response:
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, body: bytes | Exception) -> None:
        self._body = body

    def read(self) -> bytes:
        if isinstance(self._body, Exception):
            raise self._body
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


@pytest.fixture(autouse=True)
def fresh_deadline(monkeypatch):
    """Every test starts with the retry deadline far away.

    Otherwise the tests would inherit however long the interpreter had been up.
    """
    monkeypatch.setattr(builder, "_STARTED", time.monotonic())


class _Urlopen:
    """A urlopen double that plays out one outcome per call, and logs the calls.

    A class rather than a closure with an attribute bolted on, so that the
    call log is a declared member and the tests type-check.
    """

    def __init__(self, *outcomes) -> None:
        self._remaining = list(outcomes)
        self.calls: list[str] = []
        self.timeouts: list[int | None] = []

    def __call__(self, request, timeout=None) -> _Response:
        self.calls.append(request.full_url)
        self.timeouts.append(timeout)
        outcome = self._remaining.pop(0)
        if isinstance(outcome, _OnRead):
            return _Response(outcome.error)
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


def test_get_passes_the_caller_s_timeout_to_every_attempt(monkeypatch):
    """A retry must not quietly widen or drop the socket timeout.

    The deadline above only bounds the build if each attempt gives up when it
    was told to.
    """
    urlopen = _Urlopen(ConnectionResetError("reset by peer"), b"listing")
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    builder._get(URL, timeout=60)

    assert urlopen.timeouts == [60, 60]


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


def test_get_stops_retrying_once_the_job_is_nearly_out_of_time(
    monkeypatch, no_sleeping
):
    """Late in the run a failure is reported rather than retried.

    Retrying past the deadline only makes it likelier that GitHub kills the job
    before it can publish anything, which is worse than one reported failure.
    """
    monkeypatch.setattr(
        builder,
        "_STARTED",
        time.monotonic() - builder.RETRY_DEADLINE.total_seconds() - 1,
    )
    urlopen = _Urlopen(urllib.error.URLError(TimeoutError("timed out")), b"listing")
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    with pytest.raises(urllib.error.URLError):
        builder._get(URL, timeout=60)

    assert len(urlopen.calls) == 1
    assert no_sleeping == []


def test_get_retries_a_body_that_stops_midway(monkeypatch, no_sleeping):
    """A truncated 7 MB download is not an OSError, and still deserves a retry.

    It surfaces from read(), not from urlopen, so the retry has to cover the
    body transfer and not only the connect.
    """
    urlopen = _Urlopen(
        _OnRead(http.client.IncompleteRead(b"half a grib", 5_000_000)),
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


# Spelled out rather than read from builder.RETRY_STATUS: parametrising over the
# implementation's own set means removing a code from it also removes the case
# that would have caught the removal.
@pytest.mark.parametrize("code", [408, 425, 429])
def test_get_retries_the_statuses_that_mean_ask_again(monkeypatch, no_sleeping, code):
    """408, 425 and 429 are the server asking to be asked again, not a refusal.

    They are the only 4xx worth another attempt, and 408 in particular is the
    same failure as a client-side timeout with the server reporting it instead.
    """
    urlopen = _Urlopen(_http_error(code), b"listing")
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    assert builder._get(URL) == b"listing"
    assert len(urlopen.calls) == 2


@pytest.mark.parametrize("code", [400, 403, 404, 410, 451])
def test_get_does_not_retry_a_refusal(monkeypatch, no_sleeping, code):
    """A plain 4xx must come straight back.

    load_stations asks for today's metadata first and falls back to yesterday's
    when it fails. Retrying the 404 would only delay that fallback, and metadata
    for the current UTC day is legitimately absent for the first minutes of it.
    """
    urlopen = _Urlopen(_http_error(code), b"never reached")
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    with pytest.raises(urllib.error.HTTPError) as raised:
        builder._get(URL, timeout=60)

    assert raised.value.code == code
    assert len(urlopen.calls) == 1
    assert no_sleeping == []


def test_load_stations_still_falls_back_to_yesterday(monkeypatch, no_sleeping):
    """The 404 fallback survives the retry loop being added under it."""
    urlopen = _Urlopen(
        _http_error(404),
        b'{"data": {"data": {"values": ['
        b'["0-20000-0-11518", 1, "Praha", 14.4, 50.1, 300]]}}}',
    )
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    stations = builder.load_stations()

    assert [s["station_id"] for s in stations] == ["0-20000-0-11518"]
    today = datetime.now(UTC)
    assert urlopen.calls == [
        f"{builder.STATION_METADATA}/meta1-{today:%Y%m%d}.json",
        f"{builder.STATION_METADATA}/meta1-{today - timedelta(days=1):%Y%m%d}.json",
    ], "today's file was retried instead of falling back to yesterday's"
    assert no_sleeping == []


def test_load_stations_falls_back_when_todays_metadata_is_truncated(
    monkeypatch, no_sleeping
):
    """A truncated body is the failure _get retries, so it must reach the fallback.

    It is not an OSError, so catching only that would let it out of build() and
    yesterday's file would never be asked for.
    """
    truncated = _OnRead(http.client.IncompleteRead(b"{", 4000))
    urlopen = _Urlopen(
        *[truncated] * builder.RETRY_ATTEMPTS,
        b'{"data": {"data": {"values": ['
        b'["0-20000-0-11518", 1, "Praha", 14.4, 50.1, 300]]}}}',
    )
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    stations = builder.load_stations()

    assert [s["station_id"] for s in stations] == ["0-20000-0-11518"]
    assert len(urlopen.calls) == builder.RETRY_ATTEMPTS + 1


INDEX = "https://lipelix.github.io/home-assistant-chmu-weather/v1/index.json"


def _raise(error: type[Exception]):
    """A stand-in whose only job is to report that it was called."""

    def stub(*_args, **_kwargs):
        raise error("called")

    return stub


def test_published_run_reads_the_run_the_site_serves(monkeypatch):
    """The run id has to come back in the form find_latest_run compares against."""
    urlopen = _Urlopen(b'{"schema": 1, "run": "2026-09-16T18:00:00Z"}')
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    assert builder.published_run(INDEX) == "2026091618"
    assert urlopen.calls == [INDEX]


def test_published_run_is_unknown_before_the_first_deploy(monkeypatch, no_sleeping):
    """A site with no index yet must not stop the build that would create one."""
    urlopen = _Urlopen(_http_error(404))
    monkeypatch.setattr(builder.urllib.request, "urlopen", urlopen)

    assert builder.published_run(INDEX) is None


@pytest.mark.parametrize(
    "body",
    [
        b"<html>404</html>",  # a Pages error page, served with a 200
        b'{"schema": 1}',  # an index from before the field existed
        b'{"schema": 1, "run": "whenever"}',  # something that is not a timestamp
    ],
)
def test_published_run_is_unknown_when_the_index_makes_no_sense(monkeypatch, body):
    """Anything unparseable means "cannot tell", which must not block a build."""
    monkeypatch.setattr(builder.urllib.request, "urlopen", _Urlopen(body))

    assert builder.published_run(INDEX) is None


def test_build_skips_the_download_when_the_site_has_the_newest_run(
    monkeypatch, tmp_path
):
    """The hourly schedule only works if a run already published costs nothing.

    Downloading is ~63 MB per parameter set, so the check has to happen before
    the station metadata is even asked for, and nothing may be written - the
    workflow reads the absence of dist as "nothing to deploy".
    """
    monkeypatch.setattr(builder, "find_latest_run", lambda: "2026091618")
    monkeypatch.setattr(builder, "published_run", lambda url: "2026091618")
    monkeypatch.setattr(builder, "load_stations", _raise(AssertionError))

    builder.build(tmp_path, published_index=INDEX)

    assert list(tmp_path.iterdir()) == []


class _GotPastTheCheck(Exception):
    """Raised by the stub standing in for the first download of a real build."""


def test_build_publishes_a_run_newer_than_the_site_s(monkeypatch, tmp_path):
    """The whole point: a run newer than the site's must get past the check."""
    monkeypatch.setattr(builder, "find_latest_run", lambda: "2026091700")
    monkeypatch.setattr(builder, "published_run", lambda url: "2026091618")
    monkeypatch.setattr(builder, "load_stations", _raise(_GotPastTheCheck))

    with pytest.raises(_GotPastTheCheck):
        builder.build(tmp_path, published_index=INDEX)


def test_build_without_a_published_index_never_asks(monkeypatch, tmp_path):
    """A local build has no site to compare against and must just build."""
    monkeypatch.setattr(builder, "find_latest_run", lambda: "2026091618")
    monkeypatch.setattr(builder, "published_run", _raise(AssertionError))
    monkeypatch.setattr(builder, "load_stations", _raise(_GotPastTheCheck))

    with pytest.raises(_GotPastTheCheck):
        builder.build(tmp_path)
