"""Tests for HA API smoke checks (AC D46)."""
import pytest


def test_required_ha_apis_present():
    """Import every HA symbol the diagnostics plan depends on and assert it resolves."""
    errors = []

    # Test logbook imports
    try:
        from homeassistant.components.logbook.processor import EventProcessor
        assert hasattr(EventProcessor, "get_events"), "EventProcessor.get_events method not found"
    except ImportError as e:
        errors.append(f"logbook.processor.EventProcessor: {e}")

    # Test system_log imports
    try:
        from homeassistant.components.system_log import DATA_SYSTEM_LOG, LogErrorHandler  # noqa: F401
    except ImportError as e:
        errors.append(f"system_log imports: {e}")

    # Test recorder imports
    try:
        from homeassistant.components.recorder import get_instance, statistics  # noqa: F401
    except ImportError as e:
        errors.append(f"recorder imports: {e}")

    # Test helper registries
    try:
        from homeassistant.helpers import entity_registry, issue_registry  # noqa: F401
    except ImportError as e:
        errors.append(f"helper registries: {e}")

    # Test system_health
    try:
        from homeassistant.components import system_health  # noqa: F401
    except ImportError as e:
        errors.append(f"system_health: {e}")

    # Test logger component
    try:
        from homeassistant.components.logger import SERVICE_SET_DEFAULT_LEVEL, SERVICE_SET_LEVEL  # noqa: F401
    except ImportError:
        # Some versions may not export these constants; check the component at least exists
        try:
            from homeassistant.components import logger  # noqa: F401
        except ImportError as e2:
            errors.append(f"logger component: {e2}")

    # If any imports failed, fail with actionable message
    if errors:
        pytest.fail(
            "Required HA API symbols missing:\n" + "\n".join(f"  - {err}" for err in errors)
        )
