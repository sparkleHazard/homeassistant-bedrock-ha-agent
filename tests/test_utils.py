"""Test the utils module."""
from custom_components.bedrock_ha_agent.utils import closest_color


def test_closest_color():
    """Test closest_color function."""
    assert closest_color((255, 0, 0)) == "red"
    assert closest_color((0, 0, 255)) == "blue"
