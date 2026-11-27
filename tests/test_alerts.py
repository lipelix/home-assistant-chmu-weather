"""Parsing ČHMÚ's CAP warnings and deciding what is in force.

The fixtures are real messages, cut down to a few ORPs (every <info> and its
texts are kept, only the other ORPs' geocodes are dropped):

- snow_2026-11-26.xml: snow, orange in 3104 from 10:04, yellow in Prague
  (1100) from 17:00, nothing in Plzeň (3209).
- storm_2026-07-17_1055.xml and _1709.xml: two updates on one storm day. At
  17:09 Blansko (6201) got "Velmi silné bouřky" (orange); Plzeň kept its
  yellow storms, with the onset moved from 13:00 to 17:07. Both carry an
  outlook.
- heat_2026-08-02.xml: heat stress and fire risk, both without an end time.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.chmu.alerts import (
    ARCHIVE_INTERVAL,
    KEEP_LAST_MESSAGE_FOR,
    WARNINGS_ARCHIVE_URL,
    WARNINGS_URL,
    WarningsFeed,
    WarningsUnavailable,
    active_events,
    area_warnings,
    changes,
    highest_level,
    newest_archive_file,
    next_change,
    parse_cap,
)

CAP = Path(__file__).parent / "fixtures" / "cap"


def _message(name: str):
    return parse_cap((CAP / name).read_bytes())


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


@pytest.fixture
def snow():
    return _message("snow_2026-11-26.xml")


@pytest.fixture
def storm_morning():
    return _message("storm_2026-07-17_1055.xml")


@pytest.fixture
def storm_evening():
    return _message("storm_2026-07-17_1709.xml")


@pytest.fixture
def heat():
    return _message("heat_2026-08-02.xml")


def test_the_message_identity_is_read(snow):
    assert snow.identifier.endswith("XOCZ50_OKPR_000420")
    assert snow.sent == _at("2026-11-26T10:06:19+01:00")


def test_no_warning_entries_are_not_warnings(snow):
    """Every phenomenon without a warning is listed as "Žádná výstraha ..."."""
    assert not any(w.event.startswith("Žádn") for w in snow.warnings)


def test_warnings_follow_the_orp(snow):
    warnings, _ = snow.for_area("3104", "cs")
    assert [(w.event, w.level) for w in warnings] == [
        ("Velmi rizikové sněhové jevy", "orange")
    ]
    assert snow.for_area("3209", "cs") == ([], [])


def test_english_home_assistant_gets_the_english_texts(snow):
    warnings, _ = snow.for_area("3104", "en")
    assert len(warnings) == 1
    assert warnings[0].language == "en-GB"
    assert warnings[0].event != "Velmi rizikové sněhové jevy"
    assert warnings[0].level == "orange"


def test_a_warning_is_in_force_only_between_onset_and_expiry(snow):
    (prague,), _ = snow.for_area("1100", "cs")
    assert prague.onset == _at("2026-11-26T17:00:00+01:00")
    assert prague.expires == _at("2026-11-27T09:00:00+01:00")

    assert not prague.is_active(snow.sent)
    assert prague.is_active(_at("2026-11-26T17:00:00+01:00"))
    assert not prague.is_active(_at("2026-11-27T09:00:00+01:00"))
    assert prague.is_expired(_at("2026-11-27T09:00:00+01:00"))


def test_the_level_counts_only_warnings_in_force(snow):
    prague, _ = snow.for_area("1100", "cs")
    assert highest_level(prague, snow.sent) == "none"
    assert highest_level(prague, _at("2026-11-26T18:00:00+01:00")) == "yellow"


def test_the_highest_level_wins(storm_evening):
    blansko, _ = storm_evening.for_area("6201", "cs")
    assert highest_level(blansko, _at("2026-07-17T17:30:00+02:00")) == "orange"
    assert highest_level(blansko, _at("2026-07-17T19:30:00+02:00")) == "yellow"
    assert highest_level(blansko, _at("2026-07-18T00:00:00+02:00")) == "none"


def test_a_warning_without_an_end_lasts(heat):
    """Heat stress and fire risk end only when a later message drops them."""
    warnings, _ = heat.for_area("1100", "cs")
    open_ended = [w for w in warnings if w.expires is None]
    assert {w.event for w in open_ended} == {
        "Velmi silná zátěž teplem",
        "Riziko požárů",
    }
    far_future = heat.sent + timedelta(days=30)
    assert all(w.is_active(far_future) for w in open_ended)
    assert highest_level(warnings, far_future) == "orange"


def test_the_outlook_is_kept_apart(storm_morning):
    warnings, outlooks = storm_morning.for_area("3209", "cs")
    assert [w.event for w in warnings] == ["Silné bouřky"]
    assert len(outlooks) == 1
    assert outlooks[0].is_outlook
    assert outlooks[0].description


def test_active_events_name_the_worst_first(storm_evening):
    blansko, _ = storm_evening.for_area("6201", "cs")
    assert active_events(blansko, _at("2026-07-17T17:30:00+02:00")) == [
        "Velmi silné bouřky",
        "Silná zátěž teplem",
    ]
    assert active_events(blansko, _at("2026-07-17T19:30:00+02:00")) == ["Silné bouřky"]
    assert active_events(blansko, _at("2026-07-18T00:00:00+02:00")) == []


def test_active_events_leave_out_what_has_not_started(snow):
    prague, _ = snow.for_area("1100", "cs")
    assert active_events(prague, snow.sent) == []
    assert active_events(prague, _at("2026-11-26T18:00:00+01:00")) == [
        "Rizikové sněhové jevy"
    ]


def test_next_change_is_the_nearest_onset_or_expiry(storm_evening):
    blansko, _ = storm_evening.for_area("6201", "cs")
    assert next_change(blansko, _at("2026-07-17T17:30:00+02:00")) == _at(
        "2026-07-17T19:00:00+02:00"
    )
    assert next_change(blansko, _at("2026-07-18T00:00:00+02:00")) is None


def test_area_warnings_are_chronological(storm_evening):
    blansko = area_warnings(storm_evening, "6201", "Blansko", "cs")
    onsets = [w.onset for w in blansko.warnings if w.onset is not None]
    assert len(onsets) == len(blansko.warnings)
    assert onsets == sorted(onsets)
    assert blansko.orp_name == "Blansko"
    assert len(blansko.outlooks) == 1


def test_an_upgraded_warning_is_issued(storm_morning, storm_evening):
    before, _ = storm_morning.for_area("6201", "cs")
    after, _ = storm_evening.for_area("6201", "cs")
    issued, cancelled = changes(before, after, storm_evening.sent)
    assert [w.event for w in issued] == ["Velmi silné bouřky"]
    assert cancelled == []


def test_a_moved_onset_is_the_same_warning(storm_morning, storm_evening):
    """ČHMÚ restates every warning with a new onset in each update."""
    before, _ = storm_morning.for_area("3209", "cs")
    after, _ = storm_evening.for_area("3209", "cs")
    assert before[0].onset != after[0].onset
    assert changes(before, after, storm_evening.sent) == ([], [])


def test_a_dropped_warning_is_cancelled(storm_morning, storm_evening):
    before, _ = storm_evening.for_area("6201", "cs")
    after, _ = storm_morning.for_area("6201", "cs")
    issued, cancelled = changes(before, after, _at("2026-07-17T17:30:00+02:00"))
    assert issued == []
    assert [w.event for w in cancelled] == ["Velmi silné bouřky"]


def test_a_warning_that_ran_out_is_not_cancelled(storm_evening):
    before, _ = storm_evening.for_area("6201", "cs")
    issued, cancelled = changes(before, [], _at("2026-07-18T00:00:00+02:00"))
    assert (issued, cancelled) == ([], [])


def test_attributes_are_plain_json(storm_evening):
    (warning, *_), _ = storm_evening.for_area("6201", "cs")
    data = warning.as_dict(_at("2026-07-17T17:30:00+02:00"))
    assert data["active"] is True
    assert data["onset"] == "2026-07-17T17:07:33+02:00"
    assert set(data) == {
        "event",
        "level",
        "severity",
        "code",
        "onset",
        "expires",
        "active",
        "description",
        "instruction",
    }


def test_not_a_cap_document_is_refused():
    with pytest.raises(ValueError, match="Not a CAP alert"):
        parse_cap(b"<html/>")


# --- fetching ---------------------------------------------------------------

LISTING = """
<a href="alert_cap_50_261200.xml">alert_cap_50_261200.xml</a>   26-May-2026 15:36   59240
<a href="alert_cap_50_170855.xml">alert_cap_50_170855.xml</a>   17-Jul-2026 08:55   1700000
<a href="alert_cap_70_241200.xml">alert_cap_70_241200.xml</a>   24-Nov-2026 14:58   59954
<a href="alert_cap_50_020805.xml">alert_cap_50_020805.xml</a>   02-Aug-2026 08:05   1600000
"""

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def _response(status: int, content: bytes = b"", etag: str | None = None):
    response = MagicMock()
    response.status_code = status
    response.content = content
    response.text = content.decode()
    response.headers = {"ETag": etag} if etag else {}
    if status >= 400:
        response.raise_for_status.side_effect = RuntimeError(f"HTTP {status}")
    return response


def test_the_archive_newest_is_by_time_not_name():
    """Names carry day-hour-minute only and are reused every month."""
    assert newest_archive_file(LISTING) == "alert_cap_50_020805.xml"
    assert newest_archive_file("") is None


def test_an_unchanged_message_is_not_downloaded_again():
    snow = (CAP / "snow_2026-11-26.xml").read_bytes()
    session = MagicMock()
    session.get.side_effect = [_response(200, snow, '"v1"'), _response(304)]
    feed = WarningsFeed(session)

    first = feed.get(NOW)
    second = feed.get(NOW + timedelta(minutes=5))

    assert second is first
    assert session.get.call_args_list[1].kwargs["headers"] == {"If-None-Match": '"v1"'}


def test_entries_polling_together_share_one_request():
    snow = (CAP / "snow_2026-11-26.xml").read_bytes()
    session = MagicMock()
    session.get.return_value = _response(200, snow, '"v1"')
    feed = WarningsFeed(session)

    feed.get(NOW)
    feed.get(NOW + timedelta(seconds=10))

    assert session.get.call_count == 1


def test_the_archive_stands_in_when_the_fixed_file_fails(caplog):
    heat = (CAP / "heat_2026-08-02.xml").read_bytes()
    urls = []

    def get(url, **_kwargs):
        urls.append(url)
        if url == WARNINGS_URL:
            return _response(404)
        if url == WARNINGS_ARCHIVE_URL:
            return _response(200, LISTING.encode())
        return _response(200, heat)

    session = MagicMock()
    session.get.side_effect = get
    feed = WarningsFeed(session)

    message = feed.get(NOW)

    assert message.identifier == parse_cap(heat).identifier
    assert urls == [
        WARNINGS_URL,
        WARNINGS_ARCHIVE_URL,
        WARNINGS_ARCHIVE_URL + "alert_cap_50_020805.xml",
    ]
    assert "falling back to the open data archive" in caplog.text

    # The archive is asked again only after ARCHIVE_INTERVAL; the fixed file
    # is tried on every poll.
    urls.clear()
    feed.get(NOW + timedelta(minutes=5))
    assert urls == [WARNINGS_URL]

    urls.clear()
    feed.get(NOW + ARCHIVE_INTERVAL + timedelta(minutes=1))
    assert urls == [WARNINGS_URL, WARNINGS_ARCHIVE_URL]


def test_both_sources_failing_is_reported():
    session = MagicMock()
    session.get.return_value = _response(503)
    with pytest.raises(WarningsUnavailable):
        WarningsFeed(session).get(NOW)


def test_a_network_blip_keeps_the_last_message(caplog):
    """Both hosts failed to resolve for a few minutes in a live run.

    The entities would have gone unavailable for a poll; only an outage of
    hours should do that.
    """
    snow = (CAP / "snow_2026-11-26.xml").read_bytes()
    session = MagicMock()
    session.get.return_value = _response(200, snow, '"v1"')
    feed = WarningsFeed(session)
    first = feed.get(NOW)

    session.get.return_value = _response(503)
    assert feed.get(NOW + timedelta(minutes=5)) is first
    assert "keeping the message" in caplog.text

    with pytest.raises(WarningsUnavailable):
        feed.get(NOW + KEEP_LAST_MESSAGE_FOR + timedelta(minutes=5))
