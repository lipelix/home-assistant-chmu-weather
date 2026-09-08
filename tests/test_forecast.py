"""Tests for the per-station forecast mapping.

The published forecast files are plain JSON, so the whole mapping is exercised
with hand written documents; nothing here touches the network. Home Assistant
is stubbed by tests/conftest.py.
"""

from datetime import UTC, datetime, timedelta

import pytest

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


def _document(hourly=None, daily=None, run=NOW, schema=1):
    return {
        "schema": schema,
        "model": "ALADIN CZ_1km",
        "run": run.isoformat().replace("+00:00", "Z"),
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
    parsed = fc.parse_forecast(_document(hourly=[_hour(0)]), NOW)
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

    assert parsed.current(mid_hour)["_valid_time"] == NOW


# --- daily aggregation -----------------------------------------------------


def test_daily_combines_published_extremes_with_hourly_aggregates():
    hourly = [
        _hour(0, precipitation=0.4, precipitation_type=1, cloud_coverage=100),
        _hour(1, precipitation=0.2, precipitation_type=1, cloud_coverage=100),
        _hour(2, wind_speed=36.0, wind_bearing=90),
    ]

    parsed = fc.parse_forecast(_document(hourly=hourly), NOW)
    day = parsed.daily[0]

    assert day["native_temperature"] == 28.8
    assert day["native_templow"] == 11.5
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
    hourly = [
        _hour(0),
        _hour(14, precipitation=2.0, precipitation_type=1, cloud_coverage=100),
        _hour(15, precipitation=2.0, precipitation_type=1, cloud_coverage=100),
    ]
    daily = [
        {"date": "2026-09-08", "temperature": 28.8, "templow": 11.5},
        {"date": "2026-09-09", "temperature": 20.0, "templow": 12.0},
    ]

    parsed = fc.parse_forecast(_document(hourly=hourly, daily=daily), NOW)
    tomorrow = parsed.daily[1]

    assert tomorrow["native_precipitation"] == 4.0
    assert tomorrow["condition"] == "rainy"


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


def test_a_run_older_than_twelve_hours_is_stale():
    parsed = fc.parse_forecast(_document(run=NOW - timedelta(hours=13)), NOW)

    assert parsed.is_stale(NOW)
    assert not parsed.is_unusable(NOW)


def test_a_run_older_than_two_days_is_unusable():
    parsed = fc.parse_forecast(_document(run=NOW - timedelta(hours=49)), NOW)

    assert parsed.is_unusable(NOW)
