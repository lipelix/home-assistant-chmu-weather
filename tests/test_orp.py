"""Matching a station's coordinates to the ORP its warnings are issued for."""

import pytest

from custom_components.chmu.orp import find_orp, load_orps, orp_names


def test_every_orp_is_shipped_once():
    """ČHMÚ addresses all 206 ORPs; each must be findable by its code."""
    codes = [orp.code for orp in load_orps()]
    assert len(codes) == 206
    assert len(set(codes)) == 206


def test_prague_uses_the_chmu_code():
    """ČSÚ lists Prague as 1000, the CAP messages as 1100."""
    names = orp_names()
    assert names["1100"] == "Hlavní město Praha"
    assert "1000" not in names


@pytest.mark.parametrize(
    ("station", "latitude", "longitude", "code"),
    [
        ("Plzeň-Mikulka", 49.764722, 13.378889, "3209"),
        ("Praha-Ruzyně", 50.1008, 14.26, "1100"),
        ("Brno-Tuřany", 49.1513, 16.6944, "6203"),
        ("Mošnov", 49.691944, 18.112778, "8112"),  # Kopřivnice
        ("Temelín", 49.197778, 14.342222, "3115"),  # Týn nad Vltavou
    ],
)
def test_stations_land_in_their_orp(station, latitude, longitude, code):
    orp = find_orp(latitude, longitude)
    assert orp is not None, station
    assert orp.code == code


def test_a_summit_on_an_orp_border_needs_its_exact_coordinates():
    """Lysá hora sits on the border of Frýdek-Místek and Frýdlant n. O.

    Its coordinates from the station metadata fall in Frýdek-Místek; a point a
    hundred metres away does not. The options let the user pick the other one.
    """
    station = find_orp(49.546111, 18.4475)
    nearby = find_orp(49.546, 18.447)
    assert station is not None and station.name == "Frýdek-Místek"
    assert nearby is not None and nearby.name == "Frýdlant nad Ostravicí"


def test_a_station_on_the_state_border_gets_the_nearest_orp():
    """Višňová stands on the border with Poland.

    The simplified boundary leaves it just outside every polygon; it is the
    only one of the 474 stations that does.
    """
    orp = find_orp(50.96594, 15.01814)
    assert orp is not None
    assert orp.name == "Frýdlant"


def test_a_point_abroad_has_no_orp():
    assert find_orp(48.2, 16.37) is None  # Vienna
