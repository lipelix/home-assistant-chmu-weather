"""ČHMÚ weather warnings (výstrahy SIVS) from the CAP feed.

ČHMÚ publishes its warnings as CAP 1.2 XML. One message is the complete current
state for the whole country: one <info> per phenomenon and language (cs and
en-GB), each listing the ORPs it applies to by ČSÚ code (geocode CISORP). The
messages also carry what is *not* a warning - "Žádná výstraha ..." entries for
every phenomenon without one, the outlook ("Výhled nebezpečných jevů", event
code OUTLOOK) and hydrological notes ("Dotok") - so a warning is recognised by
its awareness level: "2; yellow; Moderate", "3; orange; Severe" or
"4; red; Extreme".

Two places serve the message:

- WARNINGS_URL, the fixed file behind the CAP download on ČHMÚ's warnings site.
  It answers conditional requests with 304, so polling it every few minutes
  costs nothing until ČHMÚ issues a new message (once or twice a day, more
  during summer storms). It belongs to that web app rather than to the
  documented open data and has moved once already (data -> data2).
- WARNINGS_ARCHIVE_URL, the official open data archive. It has no fixed name
  for the newest message: the files are named by day and time, the newest has
  to be found in a ~100 kB listing, and the listing ignores conditional
  requests. It is the fallback, asked at most every ARCHIVE_INTERVAL.

Both carry the same message. Nothing here imports Home Assistant.
"""

from __future__ import annotations

import logging
import re
import threading
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from .api import new_session

_LOGGER = logging.getLogger(__name__)

WARNINGS_URL = "https://vystrahy-cr.chmi.cz/data2/XOCZ50_OKPR.xml"
WARNINGS_ARCHIVE_URL = "https://opendata.chmi.cz/meteorology/weather/alerts/cap/"
WARNINGS_WEB = "https://vystrahy-cr.chmi.cz/"

# Several config entries poll the same national file; within this window they
# share one request.
SHARED_FETCH_WINDOW = timedelta(seconds=60)
ARCHIVE_INTERVAL = timedelta(minutes=30)
# A failed poll keeps serving the last message for this long. A network blip
# must not turn the warning entities unavailable, which automations would see
# as a change; hours without any answer must.
KEEP_LAST_MESSAGE_FOR = timedelta(hours=3)
REQUEST_TIMEOUT = 60

CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}

# Awareness level colour -> rank, as ČHMÚ colours its warnings map.
LEVELS = {"yellow": 1, "orange": 2, "red": 3}
LEVEL_NONE = "none"

OUTLOOK_CODE = "OUTLOOK"

ARCHIVE_FILE = re.compile(
    r'href="(alert_cap_50_\d{6}\.xml)">[^<]*</a>\s+(\d{2}-\w{3}-\d{4} \d{2}:\d{2})'
)


class WarningsUnavailable(Exception):
    """Neither source produced a usable message."""


@dataclass(frozen=True)
class WeatherWarning:
    """One warning (or the outlook) for a set of ORPs, in one language."""

    event: str
    code: str
    level: str | None
    severity: str
    onset: datetime | None
    expires: datetime | None
    description: str
    instruction: str
    language: str
    areas: frozenset[str] = field(repr=False)

    @property
    def key(self) -> tuple[str, str]:
        """What identifies the same warning from one message to the next.

        Neither the onset nor the texts are part of it: ČHMÚ moves both when it
        updates a warning. A warning raised to a higher level is a different
        phenomenon with its own code (X.1 "Silné bouřky" -> X.2 "Velmi silné
        bouřky"), so it shows up as a new warning, which it is.
        """
        return (self.code, self.event)

    @property
    def is_outlook(self) -> bool:
        return self.code == OUTLOOK_CODE

    def is_active(self, now: datetime) -> bool:
        """In force now: started, and not over.

        A warning without an end time (fire risk, heat stress, flood vigilance)
        lasts until a later message drops it.
        """
        started = self.onset is None or self.onset <= now
        return started and not self.is_expired(now)

    def is_expired(self, now: datetime) -> bool:
        return self.expires is not None and self.expires <= now

    def as_dict(self, now: datetime) -> dict[str, Any]:
        """Attributes and event data: plain JSON types only."""
        return {
            "event": self.event,
            "level": self.level,
            "severity": self.severity,
            "code": self.code,
            "onset": self.onset.isoformat() if self.onset else None,
            "expires": self.expires.isoformat() if self.expires else None,
            "active": self.is_active(now),
            "description": self.description,
            "instruction": self.instruction,
        }


@dataclass(frozen=True)
class CapMessage:
    """One CAP message: the national state of warnings when it was sent."""

    identifier: str
    sent: datetime
    warnings: tuple[WeatherWarning, ...]

    def for_area(
        self, orp_code: str, language: str
    ) -> tuple[list[WeatherWarning], list[WeatherWarning]]:
        """Return (warnings, outlooks) for one ORP in the best language."""
        chosen = _pick_language(self.warnings, language)
        relevant = [
            warning
            for warning in self.warnings
            if warning.language == chosen and orp_code in warning.areas
        ]
        return (
            [warning for warning in relevant if not warning.is_outlook],
            [warning for warning in relevant if warning.is_outlook],
        )


@dataclass(frozen=True)
class AreaWarnings:
    """What one message says about one ORP, in one language."""

    identifier: str
    sent: datetime
    orp_code: str
    orp_name: str
    warnings: tuple[WeatherWarning, ...]
    outlooks: tuple[WeatherWarning, ...]


def area_warnings(
    message: CapMessage, orp_code: str, orp_name: str, language: str
) -> AreaWarnings:
    """Narrow the national message down to one ORP."""
    warnings, outlooks = message.for_area(orp_code, language)
    return AreaWarnings(
        identifier=message.identifier,
        sent=message.sent,
        orp_code=orp_code,
        orp_name=orp_name,
        warnings=tuple(sorted(warnings, key=_chronological)),
        outlooks=tuple(sorted(outlooks, key=_chronological)),
    )


def _chronological(warning: WeatherWarning) -> tuple[datetime, str]:
    return (warning.onset or datetime.min.replace(tzinfo=UTC), warning.event)


def _pick_language(warnings: Iterable[WeatherWarning], language: str) -> str:
    """Czech for a Czech Home Assistant, English otherwise.

    Matched on the primary subtag, so "cs" picks "cs" and "en" picks "en-GB".
    """
    available = {warning.language for warning in warnings}
    wanted = "cs" if language.lower().startswith("cs") else "en"
    for candidate in sorted(available):
        if candidate.lower().split("-")[0] == wanted:
            return candidate
    return "cs"


def _text(element: ET.Element, tag: str) -> str:
    return (element.findtext(f"cap:{tag}", default="", namespaces=CAP_NS)).strip()


def _time(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _pairs(element: ET.Element, tag: str) -> list[tuple[str, str]]:
    return [
        (_text(item, "valueName"), _text(item, "value"))
        for item in element.findall(f"cap:{tag}", CAP_NS)
    ]


def _level(awareness_level: str) -> str | None:
    """Return the colour of "2; yellow; Moderate", or None for anything else."""
    parts = [part.strip().lower() for part in awareness_level.split(";")]
    return parts[1] if len(parts) > 1 and parts[1] in LEVELS else None


def _parse_info(info: ET.Element) -> WeatherWarning | None:
    """Return the warning or outlook an <info> describes, None if neither."""
    codes = _pairs(info, "eventCode")
    parameters = dict(_pairs(info, "parameter"))
    code = next((value for name, value in codes if name == "SIVS"), "")
    code = code or next((value for _, value in codes), "")

    level = _level(parameters.get("awareness_level", ""))
    if level is None and code != OUTLOOK_CODE:
        return None

    areas = frozenset(
        value
        for area in info.findall("cap:area", CAP_NS)
        for name, value in _pairs(area, "geocode")
        if name == "CISORP"
    )
    return WeatherWarning(
        event=_text(info, "event"),
        code=code,
        level=level,
        severity=_text(info, "severity"),
        onset=_time(_text(info, "onset")),
        expires=_time(_text(info, "expires") or parameters.get("eventEndingTime", "")),
        description=_text(info, "description"),
        instruction=_text(info, "instruction"),
        language=_text(info, "language"),
        areas=areas,
    )


def parse_cap(document: bytes) -> CapMessage:
    """Parse one ČHMÚ CAP message."""
    root = ET.fromstring(document)
    if root.tag != f"{{{CAP_NS['cap']}}}alert":
        raise ValueError(f"Not a CAP alert: {root.tag}")
    sent = _time(_text(root, "sent"))
    if sent is None:
        raise ValueError("CAP alert has no sent time")
    warnings = tuple(
        warning
        for info in root.findall("cap:info", CAP_NS)
        if (warning := _parse_info(info)) is not None
    )
    return CapMessage(
        identifier=_text(root, "identifier"), sent=sent, warnings=warnings
    )


def highest_level(warnings: Iterable[WeatherWarning], now: datetime) -> str:
    """Return the colour of the most severe warning in force, or "none"."""
    active = [
        warning.level
        for warning in warnings
        if warning.level is not None and warning.is_active(now)
    ]
    return max(active, key=LEVELS.__getitem__, default=LEVEL_NONE)


def next_change(warnings: Iterable[WeatherWarning], now: datetime) -> datetime | None:
    """Return when the set of warnings in force next changes on its own."""
    moments = [
        moment
        for warning in warnings
        for moment in (warning.onset, warning.expires)
        if moment is not None and moment > now
    ]
    return min(moments, default=None)


def changes(
    previous: Iterable[WeatherWarning],
    current: Iterable[WeatherWarning],
    now: datetime,
) -> tuple[list[WeatherWarning], list[WeatherWarning]]:
    """Return (issued, cancelled) between two messages for one ORP.

    Only warnings that have not expired count on either side. A warning that
    simply ran out is not cancelled, and a new warning of a kind that expired
    earlier is still issued.
    """
    before = {w.key: w for w in previous if not w.is_expired(now)}
    after = {w.key: w for w in current if not w.is_expired(now)}
    issued = [warning for key, warning in after.items() if key not in before]
    cancelled = [warning for key, warning in before.items() if key not in after]
    return issued, cancelled


class WarningsFeed:
    """Fetches the national CAP message once for every config entry.

    Blocking; call from the executor. Safe to call from several threads.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or new_session()
        self._lock = threading.Lock()
        self._message: CapMessage | None = None
        self._etag: str | None = None
        self._checked: datetime | None = None
        self._archive_checked: datetime | None = None
        self._archive_file: str | None = None
        self._using_archive = False
        self._succeeded: datetime | None = None

    def get(self, now: datetime) -> CapMessage:
        """Return the current message, downloading it only when it changed."""
        with self._lock:
            if (
                self._message is not None
                and self._checked is not None
                and now - self._checked < SHARED_FETCH_WINDOW
            ):
                return self._message

            try:
                message = self._fetch_latest()
                if self._using_archive:
                    _LOGGER.info("ČHMÚ warnings are back on %s", WARNINGS_URL)
                    self._using_archive = False
            except Exception as err:  # any failure means fallback
                if not self._using_archive:
                    _LOGGER.warning(
                        "ČHMÚ warnings could not be read from %s (%s), "
                        "falling back to the open data archive",
                        WARNINGS_URL,
                        err,
                    )
                    self._using_archive = True
                try:
                    message = self._fetch_archive(now)
                except WarningsUnavailable as unavailable:
                    if (
                        self._message is None
                        or self._succeeded is None
                        or now - self._succeeded > KEEP_LAST_MESSAGE_FOR
                    ):
                        raise
                    _LOGGER.warning(
                        "ČHMÚ warnings unavailable (%s), keeping the message from %s",
                        unavailable,
                        self._message.sent.isoformat(),
                    )
                    return self._message

            self._message = message
            self._checked = now
            self._succeeded = now
            return message

    def _fetch_latest(self) -> CapMessage:
        headers = {"If-None-Match": self._etag} if self._etag else {}
        response = self._session.get(
            WARNINGS_URL, headers=headers, timeout=REQUEST_TIMEOUT
        )
        if response.status_code == 304 and self._message is not None:
            return self._message
        response.raise_for_status()
        message = parse_cap(response.content)
        self._etag = response.headers.get("ETag")
        return message

    def _fetch_archive(self, now: datetime) -> CapMessage:
        if (
            self._message is not None
            and self._archive_checked is not None
            and now - self._archive_checked < ARCHIVE_INTERVAL
        ):
            return self._message

        try:
            listing = self._session.get(WARNINGS_ARCHIVE_URL, timeout=REQUEST_TIMEOUT)
            listing.raise_for_status()
            newest = newest_archive_file(listing.text)
            if newest is None:
                raise WarningsUnavailable("the archive lists no warning messages")
            if newest != self._archive_file or self._message is None:
                response = self._session.get(
                    WARNINGS_ARCHIVE_URL + newest, timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                self._message = parse_cap(response.content)
                self._archive_file = newest
                # The fixed file must be downloaded in full once it is back.
                self._etag = None
        except WarningsUnavailable:
            raise
        except Exception as err:
            raise WarningsUnavailable(f"open data archive: {err}") from err

        self._archive_checked = now
        return self._message


def newest_archive_file(listing: str) -> str | None:
    """Return the most recently written message in the archive listing.

    The names carry only day, hour and minute and are reused month after
    month, so the modification time decides, not the name.
    """
    files = [
        (datetime.strptime(stamp, "%d-%b-%Y %H:%M"), name)
        for name, stamp in ARCHIVE_FILE.findall(listing)
    ]
    return max(files)[1] if files else None
