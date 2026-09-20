"""Hand the hourly statistics built from a ČHMÚ batch to the recorder.

Split from statistics.py so the aggregation stays importable without Home
Assistant. Everything here needs the recorder, which the manifest names as an
after_dependency rather than a dependency: statistics are worth having but the
measured sensors are the point, and an installation that deliberately runs
without a recorder must still get them.
"""

import logging
from datetime import datetime
from typing import Any, cast

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .statistics import (
    STATISTIC_ELEMENTS,
    HourlyStatistic,
    build_hourly_statistics,
    hours_covered,
    newest_hour,
    statistic_id,
)

_LOGGER = logging.getLogger(__name__)

# mean_type and unit_class replaced has_mean in recent cores and become
# mandatory in 2026.11, but a HACS install may still be running a core that
# knows neither and rejects the unknown keys. Detected once, here.
try:
    from homeassistant.components.recorder.models import StatisticMeanType

    _CIRCULAR_MEAN = StatisticMeanType.CIRCULAR
    _ARITHMETIC_MEAN = StatisticMeanType.ARITHMETIC
except ImportError:  # pragma: no cover - only reached on an older core
    StatisticMeanType = None
    _CIRCULAR_MEAN = None
    _ARITHMETIC_MEAN = None


class StatisticsImporter:
    """Write one station's hourly statistics into the recorder.

    ČHMÚ republishes the same rows for as long as an hour, so the same hour is
    offered again on every poll. That is intentional and cheap: the recorder
    replaces a row with the same statistic id and start, so an hour that is
    still filling up ends up complete, and nothing is counted twice.
    """

    def __init__(self, hass: HomeAssistant, station_id: str, station_name: str) -> None:
        """Remember the station these statistics belong to."""
        self._hass = hass
        self._station_id = station_id
        self._station_name = station_name
        # The oldest hour still worth writing. None until the first import, so
        # a restart backfills every hour the published file still carries.
        self._imported_from: datetime | None = None
        self._warned_about_recorder = False

    def async_import(self, data: dict) -> None:
        """Import the hours held by one poll's data. Must not raise.

        Called from the coordinator's update, so a statistics problem has to
        cost the statistics only: the measured sensors are what the integration
        is for, and they are fine whatever the recorder makes of this.
        """
        try:
            self._async_import(data)
        except Exception:
            _LOGGER.exception(
                "Could not import ČHMÚ statistics for station %s", self._station_id
            )

    def _async_import(self, data: dict) -> None:
        """Build the statistics for this poll and queue them."""
        history = data.get("history")
        if not history:
            return

        if "recorder" not in self._hass.config.components:
            if not self._warned_about_recorder:
                self._warned_about_recorder = True
                _LOGGER.warning(
                    "No recorder is set up, so the 10 minute ČHMÚ measurements "
                    "for station %s cannot be kept as hourly statistics",
                    self._station_id,
                )
            return

        statistics = build_hourly_statistics(history, since=self._imported_from)
        if not statistics:
            return

        for key, rows in statistics.items():
            async_add_external_statistics(
                self._hass, self._metadata(key), [_as_row(row) for row in rows]
            )

        self._imported_from = newest_hour(statistics)
        _LOGGER.debug(
            "Imported %d hours of ČHMÚ statistics for station %s (%s)",
            hours_covered(statistics),
            self._station_id,
            ", ".join(sorted(statistics)),
        )

    def _metadata(self, key: str) -> StatisticMetaData:
        """Describe one element's statistic to the recorder."""
        spec = STATISTIC_ELEMENTS[key]
        metadata: dict[str, Any] = {
            "has_sum": False,
            # Shown in the statistics UI, where the station is not otherwise
            # visible - these rows belong to no entity.
            "name": f"{self._station_name} {key.replace('_', ' ')}",
            "source": DOMAIN,
            "statistic_id": statistic_id(self._station_id, key),
            "unit_of_measurement": spec.unit_of_measurement,
        }

        if StatisticMeanType is None:  # pragma: no cover - only on an older core
            metadata["has_mean"] = True
            return cast(StatisticMetaData, metadata)

        metadata["mean_type"] = _CIRCULAR_MEAN if spec.circular else _ARITHMETIC_MEAN
        metadata["unit_class"] = spec.unit_class
        return cast(StatisticMetaData, metadata)


def _as_row(statistic: HourlyStatistic) -> StatisticData:
    """Convert one built hour into the recorder's row shape."""
    row: dict[str, Any] = {"start": statistic.start, "mean": statistic.mean}
    if statistic.minimum is not None:
        row["min"] = statistic.minimum
    if statistic.maximum is not None:
        row["max"] = statistic.maximum
    if statistic.mean_weight is not None:
        row["mean_weight"] = statistic.mean_weight
    return cast(StatisticData, row)
