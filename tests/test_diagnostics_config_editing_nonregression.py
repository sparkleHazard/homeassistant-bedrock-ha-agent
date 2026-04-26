"""Non-regression tests for existing config-editing tests."""
import pytest


def test_existing_config_editing_tests_still_import():
    """Import existing config-editing test modules to catch accidental breakage."""
    errors = []

    # Try importing key existing test modules
    test_modules = [
        "tests.test_config_editing_automation",
        "tests.test_config_editing_usage",
    ]

    for module_name in test_modules:
        try:
            __import__(module_name)
        except ImportError as e:
            errors.append(f"{module_name}: {e}")

    if errors:
        pytest.fail(
            "Existing config-editing test imports failed:\n" +
            "\n".join(f"  - {err}" for err in errors)
        )
