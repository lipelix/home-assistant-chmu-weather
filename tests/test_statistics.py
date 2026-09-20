"""Tests for folding a ČHMÚ batch into hourly statistics."""

import math
from datetime import UTC, datetime
from importlib import import_module

import pytest

statistics = import_module("custom_components.chmu.statistics")


def _rows(hour: str, values: list[float], minute_step: int = 10) -> list[list]:
    """Build [timestamp, value] rows inside one UTC hour."""
    return [
        [f"{hour}:{index * minute_step:02d}:00Z", value]
        for index, value in enumerate(values)
    ]


def test_an_hour_of_rows_becomes_one_row_with_min_mean_max():
    """The five readings the sensor drops still describe their hour."""
    history = {
        "temperature": _rows("2026-09-12T18", [18.1, 17.8, 17.7, 17.1, 16.9, 17.0])
    }

    built = statistics.build_hourly_statistics(history)

    assert list(built) == ["temperature"]
    (hour,) = built["temperature"]
    assert hour.start == datetime(2026, 9, 12, 18, tzinfo=UTC)
    assert hour.minimum == 16.9
    assert hour.maximum == 18.1
    assert hour.mean == pytest.approx(17.433, abs=0.001)


def test_statistics_are_split_per_hour():
    """Rows from two hours must not be averaged together."""
    history = {
        "temperature": _rows("2026-09-12T18", [18.0, 18.0, 18.0, 18.0, 18.0, 18.0])
        + _rows("2026-09-12T19", [12.0, 12.0])
    }

    built = statistics.build_hourly_statistics(history)

    assert [hour.start.hour for hour in built["temperature"]] == [18, 19]
    assert [hour.mean for hour in built["temperature"]] == [18.0, 12.0]


def test_hours_are_returned_oldest_first():
    """The recorder is handed a series, so the order has to be the clock's."""
    history = {
        "temperature": _rows("2026-09-12T19", [12.0]) + _rows("2026-09-12T18", [18.0])
    }

    built = statistics.build_hourly_statistics(history)

    assert [hour.start.hour for hour in built["temperature"]] == [18, 19]


def test_since_keeps_the_hour_it_names():
    """The newest hour is still filling up, so it is rebuilt, not skipped.

    ČHMÚ publishes an hour's six rows in one batch, but the file is re-read
    every 10 minutes; dropping the hour already imported would freeze it at
    whatever it held the first time it was seen.
    """
    history = {
        "temperature": _rows("2026-09-12T17", [10.0])
        + _rows("2026-09-12T18", [18.0])
        + _rows("2026-09-12T19", [12.0])
    }

    built = statistics.build_hourly_statistics(
        history, since=datetime(2026, 9, 12, 18, tzinfo=UTC)
    )

    assert [hour.start.hour for hour in built["temperature"]] == [18, 19]


def test_newest_hour_is_what_to_resume_from():
    """The resume point is the newest hour across all elements."""
    history = {
        "temperature": _rows("2026-09-12T18", [18.0]),
        "humidity": _rows("2026-09-12T19", [55.0]),
    }

    built = statistics.build_hourly_statistics(history)

    assert statistics.newest_hour(built) == datetime(2026, 9, 12, 19, tzinfo=UTC)
    assert statistics.newest_hour({}) is None
    assert statistics.hours_covered(built) == 2


def test_wind_direction_uses_a_circular_mean():
    """Averaging 350° and 10° arithmetically would point due south."""
    history = {"wind_direction": _rows("2026-09-12T18", [350.0, 10.0])}

    (hour,) = statistics.build_hourly_statistics(history)["wind_direction"]

    assert hour.mean == pytest.approx(0.0, abs=0.001) or hour.mean == pytest.approx(
        360.0, abs=0.001
    )
    # An angle has no meaningful minimum or maximum.
    assert hour.minimum is None
    assert hour.maximum is None
    # Two rows pointing 20° apart, each standing for 10 minutes.
    assert hour.mean_weight == pytest.approx(
        2 * statistics.ROW_DURATION_SECONDS * math.cos(math.radians(10)), abs=0.001
    )


def test_a_missed_measurement_costs_only_its_own_row():
    """ČHMÚ leaves a failed measurement in the file as an empty value."""
    history = {
        "temperature": [
            ["2026-09-12T18:00:00Z", 18.0],
            ["2026-09-12T18:10:00Z", ""],
            ["2026-09-12T18:20:00Z", None],
            ["2026-09-12T18:30:00Z", 16.0],
            ["2026-09-12T18:40:00Z"],
            ["not a timestamp", 99.0],
        ]
    }

    (hour,) = statistics.build_hourly_statistics(history)["temperature"]

    assert hour.mean == 17.0
    assert (hour.minimum, hour.maximum) == (16.0, 18.0)


def test_an_hour_with_nothing_usable_is_left_out():
    """An element that reported nothing must not become an empty series."""
    history = {"temperature": [["2026-09-12T18:00:00Z", ""]], "pressure": []}

    assert statistics.build_hourly_statistics(history) == {}


def test_precipitation_is_not_imported():
    """Its rows are ambiguous - see the note in statistics.py."""
    history = {"precipitation": _rows("2026-09-12T18", [0.2, 0.0])}

    assert statistics.build_hourly_statistics(history) == {}


def test_timestamps_without_a_zone_are_read_as_utc():
    """ČHMÚ names its files after the UTC day and stamps rows in UTC."""
    history = {"temperature": [["2026-09-12T18:30:00", 18.0]]}

    (hour,) = statistics.build_hourly_statistics(history)["temperature"]

    assert hour.start == datetime(2026, 9, 12, 18, tzinfo=UTC)


def test_an_offset_timestamp_is_converted_before_the_hour_is_taken():
    """20:30+02:00 belongs to the 18:00 UTC hour, not the 20:00 one."""
    history = {"temperature": [["2026-09-12T20:30:00+02:00", 18.0]]}

    (hour,) = statistics.build_hourly_statistics(history)["temperature"]

    assert hour.start == datetime(2026, 9, 12, 18, tzinfo=UTC)


@pytest.mark.parametrize(
    ("station_id", "expected"),
    [
        ("11450", "chmu:11450_temperature"),
        ("0-203-0-CHOMUTOV", "chmu:0_203_0_chomutov_temperature"),
        # Not a real id, but one the recorder would reject outright.
        ("Praha--Ruzyne_", "chmu:praha_ruzyne_temperature"),
    ],
)
def test_statistic_ids_are_slugs(station_id, expected):
    """A statistic id has the same character rules as an entity id."""
    assert statistics.statistic_id(station_id, "temperature") == expected
