"""Tests for the per-station forecast mapping.

The published forecast files are plain JSON, so the whole mapping is exercised
with hand written documents; nothing here touches the network. Home Assistant
is stubbed by tests/conftest.py.
"""

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests

from custom_components.chmu import forecast as fc

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _hour(offset: int, **overrides):
    """Build one published hourly row, NOW + offset hours."""
    row = {
        "datetime": (NOW + timedelta(hours=offset)).isoformat().replace("+00:00", "Z"),
        "temperature": 20.0,
        "humidity": 50,
        "cloud_coverage": 0,
        "wind_speed": 18.0,
        "wind_bearing": 270,
        "precipitation_type": 0,
        "precipitation": 0.0,
    }
    row.update(overrides)
    return row


def _series(*amounts, first_offset=0, **shared):
    """Build contiguous hourly rows, one per precipitation amount.

    The publisher never emits gaps, and the precipitation shift is only
    meaningful on a contiguous series, so tests that care about amounts build
    their hours this way rather than picking isolated offsets.
    """
    return [
        _hour(
            first_offset + i,
            precipitation=amount,
            precipitation_type=1 if amount else 0,
            **shared,
        )
        for i, amount in enumerate(amounts)
    ]


def _document(hourly=None, daily=None, run=NOW, schema=1, generated=...):
    return {
        "schema": schema,
        "model": "ALADIN CZ_1km",
        "run": run.isoformat().replace("+00:00", "Z"),
        # Defaults to the run time; the publisher stamps the real publication
        # time, which is what staleness is measured from.
        "generated": (run if generated is ... else generated)
        .isoformat()
        .replace("+00:00", "Z"),
        "station": {
            "station_id": "0-20000-0-11450",
            "name": "Plzeň, Mikulka",
            "latitude": 49.764722,
            "longitude": 13.378889,
            "elevation": 359.8,
        },
        "hourly": hourly if hourly is not None else [_hour(0)],
        "daily": daily
        if daily is not None
        else [{"date": "2026-09-08", "temperature": 28.8, "templow": 11.5}],
    }


# --- condition mapping -----------------------------------------------------


@pytest.mark.parametrize(
    ("cloud", "expected"),
    [
        (0, "sunny"),
        (24, "sunny"),
        (25, "partlycloudy"),
        (74, "partlycloudy"),
        (75, "cloudy"),
        (100, "cloudy"),
    ],
)
def test_dry_hours_are_mapped_from_cloud_cover(cloud, expected):
    assert (
        fc.condition(
            cloud_coverage=cloud,
            precipitation=0.0,
            precipitation_type=0,
            temperature=20.0,
        )
        == expected
    )


def test_a_clear_sky_at_night_is_clear_night():
    assert (
        fc.condition(
            cloud_coverage=0,
            precipitation=0.0,
            precipitation_type=0,
            temperature=12.0,
            night=True,
        )
        == "clear-night"
    )


@pytest.mark.parametrize(
    ("amount", "temperature", "expected"),
    [
        (0.5, 20.0, "rainy"),
        (4.0, 20.0, "pouring"),
        (1.0, 1.5, "snowy-rainy"),
        (1.0, 0.0, "snowy"),
    ],
)
def test_wet_hours_are_mapped_from_amount_and_temperature(
    amount, temperature, expected
):
    assert (
        fc.condition(
            cloud_coverage=100,
            precipitation=amount,
            precipitation_type=1,
            temperature=temperature,
        )
        == expected
    )


def test_precipitation_type_catches_drizzle_that_rounds_to_zero():
    # ALADIN reported a precipitation type while the hourly amount rounded to
    # 0.0 mm; the hour is still wet.
    assert (
        fc.condition(
            cloud_coverage=100,
            precipitation=0.0,
            precipitation_type=11,
            temperature=15.0,
        )
        == "rainy"
    )


def test_condition_is_unknown_without_cloud_cover():
    assert (
        fc.condition(
            cloud_coverage=None,
            precipitation=0.0,
            precipitation_type=0,
            temperature=20.0,
        )
        is None
    )


# --- day and night ---------------------------------------------------------


def test_solar_elevation_matches_known_prague_positions():
    # Prague, 2026-06-21: sun high at local noon, below the horizon at midnight.
    noon = fc.solar_elevation(datetime(2026, 6, 21, 11, 0, tzinfo=UTC), 50.08, 14.44)
    midnight = fc.solar_elevation(
        datetime(2026, 6, 21, 23, 0, tzinfo=UTC), 50.08, 14.44
    )

    assert 60 < noon < 65  # 63.4 degrees at the summer solstice
    assert midnight < 0


def test_night_follows_the_station_longitude():
    # 2026-09-08 sunrise over Plzeň is about 04:30 UTC.
    assert fc.is_night(datetime(2026, 9, 8, 3, 0, tzinfo=UTC), 49.76, 13.38)
    assert not fc.is_night(datetime(2026, 9, 8, 6, 0, tzinfo=UTC), 49.76, 13.38)


# --- document parsing ------------------------------------------------------


def test_parse_maps_units_and_keys_for_home_assistant():
    parsed = fc.parse_forecast(_document(hourly=[_hour(0), _hour(1)]), NOW)
    entry = parsed.hourly[0]

    assert parsed.station_name == "Plzeň, Mikulka"
    assert entry["native_temperature"] == 20.0
    assert entry["humidity"] == 50
    assert entry["cloud_coverage"] == 0
    assert entry["wind_bearing"] == 270
    assert entry["native_precipitation"] == 0.0
    # Published in km/h, reported in m/s to match the measured wind sensor.
    assert entry["native_wind_speed"] == 5.0


def test_parse_rejects_an_unknown_schema():
    with pytest.raises(ValueError, match="schema"):
        fc.parse_forecast(_document(schema=2), NOW)


def test_hours_before_the_current_one_are_dropped():
    document = _document(hourly=[_hour(-5), _hour(-1), _hour(0), _hour(1)])

    parsed = fc.parse_forecast(document, NOW)

    assert [e["_valid_time"] for e in parsed.hourly] == [
        NOW,
        NOW + timedelta(hours=1),
    ]


def test_current_returns_the_hour_covering_now():
    parsed = fc.parse_forecast(_document(hourly=[_hour(0), _hour(1)]), NOW)
    mid_hour = NOW + timedelta(minutes=35)
    current = parsed.current(mid_hour)

    assert current is not None
    assert current["_valid_time"] == NOW


def test_current_returns_nothing_once_the_series_runs_out():
    parsed = fc.parse_forecast(_document(hourly=[_hour(0)]), NOW)

    assert parsed.current(NOW + timedelta(hours=5)) is None


# --- precipitation interval ------------------------------------------------


def test_precipitation_is_shifted_to_the_hour_it_falls_in():
    """The publisher stamps the end of the accumulation hour, HA wants the start.

    build_forecast_data.py emits cumulative[T] - cumulative[T-1h], so the value
    published for T fell during (T-1h, T]. Home Assistant reads an entry's
    amount as falling in [T, T+1h), so entry T must carry the value published
    for T+1h.
    """
    parsed = fc.parse_forecast(_document(hourly=_series(0.0, 1.5, 0.0)), NOW)

    amounts = [e.get("native_precipitation") for e in parsed.hourly]

    # Published 0.0, 1.5, 0.0 -> the 1.5 mm fell between the first and second
    # hour, so it belongs to the first entry.
    assert amounts == [1.5, 0.0, None]


def test_a_shifted_wet_hour_drives_the_condition():
    parsed = fc.parse_forecast(
        _document(hourly=_series(0.0, 1.5, 0.0, cloud_coverage=100)), NOW
    )

    # The hour the rain actually falls in is reported as rainy, not the one
    # after it.
    assert [e["condition"] for e in parsed.hourly] == ["rainy", "cloudy", "cloudy"]


def test_the_last_hour_has_no_precipitation_to_report():
    parsed = fc.parse_forecast(_document(hourly=_series(0.0, 2.0)), NOW)

    # Nothing is published for the hour after the last one, so rather than
    # inventing a zero the key is simply absent.
    assert "native_precipitation" not in parsed.hourly[-1]


def test_rows_without_precipitation_keys_are_accepted():
    # The real step 0 carries no precipitation or precipitation_type at all:
    # those two ALADIN fields have 72 steps against 73 for the rest.
    bare = _hour(0)
    del bare["precipitation"]
    del bare["precipitation_type"]

    parsed = fc.parse_forecast(_document(hourly=[bare, _hour(1)]), NOW)

    assert parsed.hourly[0]["condition"] == "sunny"
    assert parsed.hourly[0]["native_precipitation"] == 0.0


# --- daily aggregation -----------------------------------------------------


def test_daily_combines_published_extremes_with_hourly_aggregates():
    hourly = _series(0.0, 0.4, 0.2, 0.0, cloud_coverage=100)
    hourly[3]["wind_speed"] = 36.0
    hourly[3]["wind_bearing"] = 90

    parsed = fc.parse_forecast(_document(hourly=hourly), NOW)
    day = parsed.daily[0]

    assert day["native_temperature"] == 28.8
    assert day["native_templow"] == 11.5
    # 0.4 + 0.2 published, shifted back one hour and summed over the day.
    assert day["native_precipitation"] == 0.6
    assert day["native_wind_speed"] == 10.0  # 36 km/h, the windiest hour
    assert day["wind_bearing"] == 90
    assert day["condition"] == "rainy"
    assert day["datetime"].startswith("2026-09-08T00:00:00")


def test_a_dry_day_is_mapped_from_daytime_cloud_cover_only():
    # Overcast after dark must not turn a clear day cloudy. NOW is 12:00 UTC,
    # so offsets 9 and 10 hours are 23:00 and 00:00 local.
    hourly = [_hour(0), _hour(1), _hour(9, cloud_coverage=100)]

    parsed = fc.parse_forecast(_document(hourly=hourly), NOW)

    assert parsed.daily[0]["cloud_coverage"] == 0
    assert parsed.daily[0]["condition"] == "sunny"


def test_overnight_rain_still_makes_the_day_rainy():
    # Regression: the daily condition used to be read from daylight hours only,
    # so a day with 10 mm of overnight rain was reported as merely cloudy.
    # NOW is 12:00 UTC, so a 14 hour offset is 04:00 local the next day.
    # 2 mm/h is rain; 4 mm/h and up would be pouring.
    hourly = _series(0.0, 2.0, 2.0, 0.0, first_offset=13, cloud_coverage=100)
    daily = [
        {"date": "2026-09-08", "temperature": 28.8, "templow": 11.5},
        {"date": "2026-09-09", "temperature": 20.0, "templow": 12.0},
    ]

    parsed = fc.parse_forecast(_document(hourly=hourly, daily=daily), NOW)
    tomorrow = parsed.daily[1]

    assert tomorrow["native_precipitation"] == 4.0
    assert tomorrow["condition"] == "rainy"


def test_a_day_without_a_high_is_dropped():
    # The 12 hour extremes mean the last day a run reaches often has only the
    # overnight low. A tile with no temperature renders empty in Home
    # Assistant, and its hours cover only part of the day.
    document = _document(
        daily=[
            {"date": "2026-09-08", "temperature": 28.8, "templow": 11.5},
            {"date": "2026-09-09", "temperature": 20.0, "templow": 12.0},
            {"date": "2026-09-10", "templow": 10.7},
        ]
    )

    parsed = fc.parse_forecast(document, NOW)

    assert [day["datetime"][:10] for day in parsed.daily] == [
        "2026-09-08",
        "2026-09-09",
    ]
    assert all("native_temperature" in day for day in parsed.daily)


def test_a_day_without_an_overnight_low_is_still_reported():
    # The first day of a run is the mirror image: it has the afternoon high but
    # the overnight low already belongs to the previous run.
    document = _document(daily=[{"date": "2026-09-08", "temperature": 29.1}])

    parsed = fc.parse_forecast(document, NOW)

    assert len(parsed.daily) == 1
    assert parsed.daily[0]["native_temperature"] == 29.1
    assert "native_templow" not in parsed.daily[0]


def test_days_already_over_are_dropped():
    document = _document(
        daily=[
            {"date": "2026-09-07", "temperature": 25.0, "templow": 10.0},
            {"date": "2026-09-08", "temperature": 28.8, "templow": 11.5},
        ]
    )

    parsed = fc.parse_forecast(document, NOW)

    assert [day["native_temperature"] for day in parsed.daily] == [28.8]


# --- staleness -------------------------------------------------------------


def test_a_fresh_run_is_neither_stale_nor_unusable():
    parsed = fc.parse_forecast(_document(run=NOW - timedelta(hours=6)), NOW)

    assert not parsed.is_stale(NOW)
    assert not parsed.is_unusable(NOW)


def test_staleness_is_measured_from_publication_not_from_the_run():
    """An old run that was just published is not a sign of a stopped job.

    The builder serves the newest model run that has every parameter, so it
    legitimately republishes an older run; GitHub also delays the schedule by
    hours. Measuring from the run time warned about a healthy pipeline.
    """
    parsed = fc.parse_forecast(
        _document(run=NOW - timedelta(hours=20), generated=NOW - timedelta(minutes=10)),
        NOW,
    )

    assert not parsed.is_stale(NOW)
    assert parsed.publication_age(NOW) < timedelta(hours=1)
    # The content is still 20 hours old, and age() keeps saying so.
    assert parsed.age(NOW) == timedelta(hours=20)


def test_a_forecast_not_published_for_eighteen_hours_is_stale():
    parsed = fc.parse_forecast(
        _document(run=NOW - timedelta(hours=20), generated=NOW - timedelta(hours=19)),
        NOW,
    )

    assert parsed.is_stale(NOW)
    assert not parsed.is_unusable(NOW)


def test_staleness_falls_back_to_the_run_without_a_publication_time():
    document = _document(run=NOW - timedelta(hours=19))
    del document["generated"]

    parsed = fc.parse_forecast(document, NOW)

    assert parsed.generated is None
    assert parsed.is_stale(NOW)


def test_a_run_older_than_two_days_is_unusable_however_fresh_the_publish():
    # Keyed on the model run on purpose: if ČHMÚ stops producing runs, the job
    # keeps republishing the same ageing content.
    parsed = fc.parse_forecast(
        _document(run=NOW - timedelta(hours=49), generated=NOW), NOW
    )

    assert parsed.is_unusable(NOW)
    assert not parsed.is_stale(NOW)


# --- the download client ---------------------------------------------------
#
# These exercise ChmuForecastApi itself: the URL it builds, the ETag round trip
# and the two ways a fetch can fail. Nothing here talks to the network - the
# session is injected.


def _live_document(age_hours: float = 0.0, steps: int = 6, published_ago=None):
    """Build a document whose run sits ``age_hours`` before the real clock.

    ChmuForecastApi reads the wall clock, so its tests cannot use the frozen
    NOW the parsing tests share.
    """
    run = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=age_hours
    )
    hourly = [
        {
            "datetime": (run + timedelta(hours=step))
            .isoformat()
            .replace("+00:00", "Z"),
            "temperature": 20.0,
            "humidity": 50,
            "cloud_coverage": 0,
            "wind_speed": 18.0,
            "wind_bearing": 270,
            "precipitation_type": 0,
            "precipitation": 0.0,
        }
        for step in range(steps)
    ]
    return {
        "schema": 1,
        "model": "ALADIN CZ_1km",
        "run": run.isoformat().replace("+00:00", "Z"),
        "generated": (
            run
            if published_ago is None
            else datetime.now(UTC) - timedelta(hours=published_ago)
        )
        .isoformat()
        .replace("+00:00", "Z"),
        "station": {
            "station_id": "0-20000-0-11450",
            "name": "Plzeň, Mikulka",
            "latitude": 49.764722,
            "longitude": 13.378889,
            "elevation": 359.8,
        },
        "hourly": hourly,
        "daily": [{"date": run.date().isoformat(), "temperature": 26.0}],
    }


def _response(status=200, payload=None, etag: str | None = 'W/"tag"'):
    """Build a fake requests response."""
    response = MagicMock()
    response.status_code = status
    response.headers = {"ETag": etag} if etag else {}
    if status >= 400:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status}"
        )
    else:
        response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _api(*responses):
    """Build a client whose injected session returns ``responses`` in order."""
    session = MagicMock()
    session.headers = {}
    session.get.side_effect = list(responses)
    return fc.ChmuForecastApi("11450", session=session), session


def test_the_client_asks_for_the_station_it_was_given():
    api, session = _api(_response(payload=_live_document()))

    api.get_forecast()

    # A bare WMO id in the config entry has to become the full WSI file name;
    # this is the one assertion that would catch a typo in either.
    assert api.url == (
        "https://lipelix.github.io/home-assistant-chmu-weather/v1/0-20000-0-11450.json"
    )
    assert session.get.call_args_list[0].args[0] == api.url


def test_an_unchanged_forecast_is_revalidated_and_reused():
    document = _live_document()
    api, session = _api(_response(payload=document), _response(status=304, etag=None))

    first = api.get_forecast()
    second = api.get_forecast()

    # The second request carries the validator and the body is never reparsed.
    assert session.get.call_args_list[1].kwargs["headers"] == {
        "If-None-Match": 'W/"tag"'
    }
    assert second.run == first.run
    assert second.station_name == "Plzeň, Mikulka"


def test_a_304_with_nothing_cached_refetches_without_the_validator():
    # Only reachable if something upstream answers a request we did not
    # condition; parsing the empty body would fail on nothing useful.
    api, session = _api(
        _response(status=304, etag=None), _response(payload=_live_document())
    )
    api._etag = 'W/"stale"'

    forecast = api.get_forecast()

    assert forecast.station_name == "Plzeň, Mikulka"
    assert session.get.call_args_list[1].kwargs.get("headers") is None


def test_an_http_error_propagates():
    api, _ = _api(_response(status=500))

    with pytest.raises(requests.exceptions.HTTPError):
        api.get_forecast()


def test_a_forecast_too_old_to_use_is_refused():
    api, _ = _api(_response(payload=_live_document(age_hours=49)))

    with pytest.raises(fc.ForecastUnusable, match="hours old"):
        api.get_forecast()


def test_a_forecast_nobody_has_republished_is_served_with_a_warning(caplog):
    api, _ = _api(_response(payload=_live_document(age_hours=20, published_ago=19)))

    with caplog.at_level(logging.WARNING):
        forecast = api.get_forecast()

    assert forecast.station_name == "Plzeň, Mikulka"
    assert "may have stopped" in caplog.text


def test_an_old_run_that_was_just_published_warns_about_nothing(caplog):
    api, _ = _api(_response(payload=_live_document(age_hours=10, published_ago=0)))

    with caplog.at_level(logging.WARNING):
        api.get_forecast()

    assert caplog.text == ""
