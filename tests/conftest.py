"""Shared test setup.

Home Assistant is not a test dependency: the integration modules are imported
against a minimal stub so the logic can be tested from a bare virtualenv. Each
test module used to build its own stub, which made the result depend on
collection order.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _ConfigEntry:
    """Stub for ConfigEntry."""

    def __class_getitem__(cls, item):
        """Accept the ConfigEntry[RuntimeData] annotation form."""
        return cls


class _Platform:
    """Stub for Platform."""

    SENSOR = "sensor"
    WEATHER = "weather"


class _HomeAssistant:
    """Stub for HomeAssistant."""


class _DataUpdateCoordinator:
    """Stub for DataUpdateCoordinator."""

    def __class_getitem__(cls, item):
        """Accept the DataUpdateCoordinator[T] annotation form."""
        return cls


class _UpdateFailed(Exception):
    """Stub for UpdateFailed."""


def _install_homeassistant_stub() -> None:
    """Register stub Home Assistant modules, unless the real ones are present.

    Checked with find_spec rather than sys.modules: the real package is only in
    sys.modules once something has imported it, so a stub installed here would
    win purely by running first.
    """
    if importlib.util.find_spec("homeassistant") is not None:
        return

    for module_path, attrs in [
        ("homeassistant", {}),
        ("homeassistant.config_entries", {"ConfigEntry": _ConfigEntry}),
        ("homeassistant.const", {"Platform": _Platform}),
        ("homeassistant.core", {"HomeAssistant": _HomeAssistant}),
        ("homeassistant.helpers", {}),
        (
            "homeassistant.helpers.update_coordinator",
            {
                "DataUpdateCoordinator": _DataUpdateCoordinator,
                "UpdateFailed": _UpdateFailed,
            },
        ),
    ]:
        module = ModuleType(module_path)
        for name, value in attrs.items():
            setattr(module, name, value)
        sys.modules[module_path] = module


_install_homeassistant_stub()
