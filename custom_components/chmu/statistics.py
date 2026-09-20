"""Hourly statistics built from the 10 minute rows ČHMÚ publishes in a batch.

ČHMÚ measures every 10 minutes but rewrites `10m-{WSI}-{date}.json` only once
an hour, at about HH:02 UTC, adding the previous hour's six rows in one go
(issue #18). The coordinator keeps the newest row per element, so five of every
six measurements are downloaded and thrown away, and the recorder history is
flat for an hour and then jumps.

Home Assistant has no API for backdating an entity state, and imported
statistics must be aligned to the top of the hour - the recorder rejects
anything else outright - so the six rows cannot be replayed as six points.
What they can do is describe their hour properly: this module folds each hour's
rows into one statistics row carrying the real hourly mean, minimum and
maximum, instead of the single reading that happened to be newest.

Kept free of Home Assistant imports on purpose: the aggregation is the part
worth testing, and the test suite runs it from a bare virtualenv. The recorder
side lives in statistics_import.py.
"""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Every published row stands for the 10 minutes it was measured in. Statistics
# weights are seconds elsewhere in Home Assistant, and a weight only matters
# for the circular mean, where it is carried into the row so the recorder can
# later aggregate hours into days.
ROW_DURATION_SECONDS = 600.0

_DEG_TO_RAD = math.pi / 180
_RAD_TO_DEG = 180 / math.pi


@dataclass(frozen=True)
class ElementStatistic:
    """How one measured element is turned into hourly statistics."""

    unit_of_measurement: str
    # Unit conversion class the recorder uses to present the statistic in the
    # user's units; None for a unit it cannot convert.
    unit_class: str | None
    # Wind direction is an angle: averaging 350° and 10° arithmetically gives
    # due south for a northerly wind, so it needs the circular mean Home
    # Assistant uses for wind bearing sensors - and a minimum and maximum of an
    # angle mean nothing, so those are left out.
    circular: bool = False


# Precipitation is deliberately absent. Which hourly figure is right depends on
# what a SRA10M row means, and the two available answers disagree: the ČHMÚ
# element metadata calls it "Srážka-10M" in mm, i.e. the amount fallen in
# those 10 minutes, which would make the hour their sum, while this
# integration has always carried it as a TOTAL_INCREASING sensor, i.e. a
# running total, which would make the hour their maximum. Every station sampled while writing this
# was dry, so nothing settled it, and importing on the wrong reading would
# invent rainfall that never fell. Left out until a wet station confirms it.
STATISTIC_ELEMENTS: dict[str, ElementStatistic] = {
    "temperature": ElementStatistic("°C", "temperature"),
    "humidity": ElementStatistic("%", "unitless"),
    "pressure": ElementStatistic("hPa", "pressure"),
    "wind_speed": ElementStatistic("m/s", "speed"),
    "wind_direction": ElementStatistic("°", None, circular=True),
}


@dataclass(frozen=True)
class HourlyStatistic:
    """One hour of measurements, ready to hand to the recorder."""

    start: datetime
    mean: float
    minimum: float | None = None
    maximum: float | None = None
    mean_weight: float | None = None


def statistic_id(station_id: str, key: str) -> str:
    """Return the external statistic id for one station element.

    Format is `<domain>:<slug>`, and the slug has the same character rules as
    an entity id: lower case, no repeated or trailing underscore. Station ids
    are either a bare WMO number ("11450") or a full WSI ("0-203-0-CHOMUTOV"),
    so the dashes and case of the latter have to go. An id the recorder would
    reject costs the statistics silently, so the slug is normalised rather than
    assumed to be well formed.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", station_id.lower()).strip("_")
    return f"chmu:{slug}_{key}"


def _as_float(value: Any) -> float | None:
    """Return value as a float, or None when it is not a number.

    ČHMÚ leaves a failed measurement as an empty string or null rather than
    omitting the row, and one bad row must not cost the whole hour.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_row_timestamp(value: Any) -> datetime | None:
    """Parse a measurement timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _circular_mean(values: list[float]) -> tuple[float, float]:
    """Return the weighted circular mean of angles in degrees and its weight.

    Same computation as the recorder's own, so an hour written here aggregates
    into a day the same way an hour it compiled itself would.
    """
    weighted_sin_sum = 0.0
    weighted_cos_sum = 0.0
    for value in values:
        radians = value * _DEG_TO_RAD
        weighted_sin_sum += math.sin(radians) * ROW_DURATION_SECONDS
        weighted_cos_sum += math.cos(radians) * ROW_DURATION_SECONDS

    return (
        (_RAD_TO_DEG * math.atan2(weighted_sin_sum, weighted_cos_sum)) % 360,
        math.sqrt(weighted_sin_sum**2 + weighted_cos_sum**2),
    )


def _hour_start(moment: datetime) -> datetime:
    """Return the top of the hour a measurement belongs to."""
    return moment.replace(minute=0, second=0, microsecond=0)


def build_hourly_statistics(
    history: dict[str, list[Any]], since: datetime | None = None
) -> dict[str, list[HourlyStatistic]]:
    """Fold a station's 10 minute rows into one statistics row per hour.

    `history` is what api.py collected from the published file: sensor key ->
    list of [timestamp, value] rows, in the order ČHMÚ published them.

    `since` drops hours that start before it. The hour it names is kept rather
    than skipped, because the newest hour in a file is still filling up: on the
    next poll it is rebuilt from more rows and rewritten, which the recorder
    handles by replacing the row with the same id and start.
    """
    result: dict[str, list[HourlyStatistic]] = {}

    for key, spec in STATISTIC_ELEMENTS.items():
        rows = history.get(key)
        if not rows:
            continue

        by_hour: dict[datetime, list[float]] = {}
        for row in rows:
            if len(row) < 2:
                continue
            measured_at = _parse_row_timestamp(row[0])
            value = _as_float(row[1])
            if measured_at is None or value is None:
                continue
            hour = _hour_start(measured_at)
            if since is not None and hour < since:
                continue
            by_hour.setdefault(hour, []).append(value)

        hourly = [
            _hourly_statistic(hour, values, spec)
            for hour, values in sorted(by_hour.items())
        ]
        if hourly:
            result[key] = hourly

    return result


def _hourly_statistic(
    hour: datetime, values: list[float], spec: ElementStatistic
) -> HourlyStatistic:
    """Summarise one hour's values the way its element needs."""
    if spec.circular:
        mean, weight = _circular_mean(values)
        return HourlyStatistic(start=hour, mean=mean, mean_weight=weight)

    return HourlyStatistic(
        start=hour,
        mean=sum(values) / len(values),
        minimum=min(values),
        maximum=max(values),
    )


def newest_hour(statistics: dict[str, list[HourlyStatistic]]) -> datetime | None:
    """Return the latest hour present, to resume from on the next poll."""
    starts = [rows[-1].start for rows in statistics.values() if rows]
    return max(starts) if starts else None


def hours_covered(statistics: dict[str, list[HourlyStatistic]]) -> int:
    """Return how many distinct hours the built statistics span, for logging."""
    return len({row.start for rows in statistics.values() for row in rows})
