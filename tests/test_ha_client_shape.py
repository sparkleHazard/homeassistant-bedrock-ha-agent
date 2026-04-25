"""Module-surface tests for ha_client subpackage (no HA instance required)."""
import inspect
import pytest

from custom_components.bedrock_ha_agent.config_tools.ha_client import (
    automation,
    script,
    scene,
    helper,
    lovelace,
    registry,
)


def test_automation_module_shape():
    """Verify automation module exposes expected functions."""
    expected = {
        "list_automations",
        "get_automation",
        "create_or_update_automation",
        "delete_automation",
        "reload_automations",
    }
    actual = {
        name
        for name, obj in inspect.getmembers(automation)
        if inspect.iscoroutinefunction(obj)
    }
    assert actual == expected, f"Missing/extra functions: {expected ^ actual}"


def test_script_module_shape():
    """Verify script module exposes expected functions."""
    expected = {
        "list_scripts",
        "get_script",
        "create_or_update_script",
        "delete_script",
        "reload_scripts",
    }
    actual = {
        name
        for name, obj in inspect.getmembers(script)
        if inspect.iscoroutinefunction(obj)
    }
    assert actual == expected, f"Missing/extra functions: {expected ^ actual}"


def test_scene_module_shape():
    """Verify scene module exposes expected functions."""
    expected = {
        "list_scenes",
        "get_scene",
        "create_or_update_scene",
        "delete_scene",
        "reload_scenes",
    }
    actual = {
        name
        for name, obj in inspect.getmembers(scene)
        if inspect.iscoroutinefunction(obj)
    }
    assert actual == expected, f"Missing/extra functions: {expected ^ actual}"


def test_helper_module_shape():
    """Verify helper module exposes expected functions."""
    expected = {
        "list_helpers",
        "get_helper",
        "create_helper",
        "update_helper",
        "delete_helper",
        "reload_helper_domain",
    }
    actual = {
        name
        for name, obj in inspect.getmembers(helper)
        if inspect.iscoroutinefunction(obj)
    }
    assert actual == expected, f"Missing/extra functions: {expected ^ actual}"


def test_helper_supported_domains():
    """Verify SUPPORTED_HELPER_DOMAINS matches plan specification."""
    expected = frozenset({
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "timer",
        "counter",
    })
    assert helper.SUPPORTED_HELPER_DOMAINS == expected


def test_lovelace_module_shape():
    """Verify lovelace module exposes expected functions."""
    expected = {
        "list_dashboards",
        "get_dashboard_mode",
        "load_dashboard",
        "save_dashboard",
        "create_dashboard",
        "update_dashboard",
        "delete_dashboard",
    }
    actual = {
        name
        for name, obj in inspect.getmembers(lovelace)
        if inspect.iscoroutinefunction(obj)
    }
    assert actual == expected, f"Missing/extra functions: {expected ^ actual}"


def test_registry_module_shape():
    """Verify registry module exposes expected functions."""
    expected = {
        "list_areas",
        "create_area",
        "update_area",
        "delete_area",
        "list_labels",
        "create_label",
        "update_label",
        "delete_label",
        "get_entity_registry_entry",
        "update_entity_registry",
        "can_toggle_disabled_by_user",
    }
    actual = {
        name
        for name, obj in inspect.getmembers(registry)
        if inspect.iscoroutinefunction(obj)
    }
    assert actual == expected, f"Missing/extra functions: {expected ^ actual}"
