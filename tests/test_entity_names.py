"""Every sensor must resolve to a name in every shipped language.

Issue #3: until v1.4.0 the English entity names were missing, so Home
Assistant had nothing to build the name from. Sensors with a device class
survived that on the device class fallback; wind direction and the weather
description have none, so they came out as "<station> None" and got an entity
id like sensor.brno_turany_none.
"""

import json
import re
from pathlib import Path

import pytest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "chmu"
TRANSLATIONS = sorted((COMPONENT / "translations").glob("*.json"))


def _translation_keys() -> set[str]:
    """Collect the translation keys the sensor platform declares."""
    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'_attr_translation_key\s*=\s*"([^"]+)"', source))
    assert keys, "no translation keys found in sensor.py"
    return keys


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda path: path.stem)
def test_translation_file_names_every_sensor(path):
    """A shipped language must name every sensor the platform creates."""
    names = (
        json.loads(path.read_text(encoding="utf-8")).get("entity", {}).get("sensor", {})
    )
    missing = sorted(
        key for key in _translation_keys() if not names.get(key, {}).get("name")
    )
    assert not missing, f"{path.name} is missing names for {missing}"


def test_english_translation_is_shipped():
    """English is the fallback language, so it cannot be the missing one."""
    assert (COMPONENT / "translations" / "en.json").is_file()


def test_strings_matches_the_english_translation():
    """strings.json is the source of the English file; keep them in sync."""
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert strings.get("entity") == english.get("entity")
