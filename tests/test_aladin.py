"""Tests for the ALADIN GRIB1 reader.

The messages are built by hand so the bit level maths is checked without
downloading tens of megabytes from ČHMÚ in CI.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from aladin import Grid, iter_messages  # noqa: E402

# 3 x 2 grid starting at 50.0 N, 14.0 E with 0.5 degree spacing.
NI, NJ = 3, 2


def _u3(value: int) -> bytes:
    return value.to_bytes(3, "big")


def _i3(value: int) -> bytes:
    return (abs(value) | (0x800000 if value < 0 else 0)).to_bytes(3, "big")


def _i2(value: int) -> bytes:
    return (abs(value) | (0x8000 if value < 0 else 0)).to_bytes(2, "big")


def _pds(*, param=11, p1=0, p2=6, tri=10, decimal_scale=0) -> bytes:
    body = bytes(
        [
            0,  # table version
            88,  # centre
            1,  # generating process
            255,  # grid id, defined in the GDS
            0x80,  # GDS present, no bitmap
            param,
            105,  # level type
        ]
    )
    body += (2).to_bytes(2, "big")  # level
    body += bytes([26, 9, 8, 0, 0])  # 2026-09-08 00:00 reference time
    body += bytes([1, p1, p2, tri])  # hour unit, P1, P2, time range indicator
    body += (0).to_bytes(2, "big")  # number averaged
    body += bytes([0, 21, 0])  # missing, century, subcentre
    body += _i2(decimal_scale)
    return _u3(len(body) + 3) + body


def _gds() -> bytes:
    body = bytes([255, 255, 0])  # NV, PV, data representation type (latlon)
    body += NI.to_bytes(2, "big") + NJ.to_bytes(2, "big")
    body += _i3(50_000) + _i3(14_000)  # La1, Lo1 in millidegrees
    body += bytes([0x88])  # resolution and component flags
    body += _i3(50_500) + _i3(15_000)  # La2, Lo2
    body += _i2(500) + _i2(500)  # Di, Dj
    body += bytes([0x40])  # scanning mode: west to east, south to north
    body += bytes(4)  # reserved
    return _u3(len(body) + 3) + body


def _bds(values: list[int], *, bits=8, binary_scale=0, reference=0.0) -> bytes:
    packed = 0
    for value in values:
        packed = (packed << bits) | value
    width = (len(values) * bits + 7) // 8
    body = bytes([0x00])  # grid point, simple packing, float, no extra flags
    body += _i2(binary_scale)
    # IBM float encoding of the reference value; only 0.0 is needed here.
    assert reference == 0.0, "test helper only encodes a zero reference value"
    body += bytes(4)
    body += bytes([bits])
    body += packed.to_bytes(width, "big")
    return _u3(len(body) + 3) + body


def _message(values: list[int], **pds_kwargs) -> bytes:
    sections = _pds(**pds_kwargs) + _gds() + _bds(values)
    total = 8 + len(sections) + 4
    return b"GRIB" + _u3(total) + bytes([1]) + sections + b"7777"


def test_grid_index_is_row_major_from_the_south_west_corner():
    grid = Grid(ni=NI, nj=NJ, lat1=50.0, lon1=14.0, di=0.5, dj=0.5)

    assert grid.index(50.0, 14.0) == 0
    assert grid.index(50.0, 15.0) == 2
    assert grid.index(50.5, 14.0) == NI
    assert grid.index(50.5, 15.0) == NI + 2


def test_grid_index_snaps_to_the_nearest_point():
    grid = Grid(ni=NI, nj=NJ, lat1=50.0, lon1=14.0, di=0.5, dj=0.5)

    assert grid.index(50.04, 14.49) == 1


def test_grid_rejects_points_outside_the_domain():
    grid = Grid(ni=NI, nj=NJ, lat1=50.0, lon1=14.0, di=0.5, dj=0.5)

    assert not grid.contains(48.0, 14.0)
    with pytest.raises(ValueError, match="outside"):
        grid.index(48.0, 14.0)


def test_reads_packed_values_at_a_point():
    message = next(iter_messages(_message([10, 20, 30, 40, 50, 60])))

    assert message.parameter == 11
    assert message.value_at(0) == pytest.approx(10.0)
    assert message.value_at(5) == pytest.approx(60.0)
    assert message.value_at(message.grid.index(50.5, 14.5)) == pytest.approx(50.0)


def test_applies_binary_and_decimal_scaling():
    sections = _pds(decimal_scale=1) + _gds() + _bds([4] * 6, binary_scale=2)
    raw = b"GRIB" + _u3(8 + len(sections) + 4) + bytes([1]) + sections + b"7777"

    message = next(iter_messages(raw))

    # (0 + 4 * 2**2) / 10**1
    assert message.value_at(0) == pytest.approx(1.6)


def test_time_range_indicator_10_uses_two_octets_for_the_step():
    message = next(iter_messages(_message([0] * 6, p1=1, p2=8, tri=10)))

    # (1 << 8) | 8 == 264 hours after the 2026-09-08 00Z reference time
    assert message.valid_time == datetime(2026, 9, 19, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("tri", "p1", "p2", "expected_hour"),
    [(0, 5, 0, 5), (1, 0, 0, 0), (4, 0, 9, 9)],
)
def test_supported_time_range_indicators(tri, p1, p2, expected_hour):
    message = next(iter_messages(_message([0] * 6, p1=p1, p2=p2, tri=tri)))

    assert message.valid_time == datetime(2026, 9, 8, expected_hour, tzinfo=UTC)


def test_rejects_an_unknown_time_range_indicator():
    with pytest.raises(ValueError, match="time range indicator"):
        next(iter_messages(_message([0] * 6, tri=3)))


def test_iterates_every_message_in_a_file():
    raw = _message([1] * 6, p2=6) + _message([2] * 6, p2=12)

    messages = list(iter_messages(raw))

    assert [m.valid_time.hour for m in messages] == [6, 12]
    assert [m.value_at(0) for m in messages] == [1.0, 2.0]
