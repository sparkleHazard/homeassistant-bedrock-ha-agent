"Test the Bedrock client functionality."""
from custom_components.bedrock_ha_agent.bedrock_client import DeviceInfo


def test_device_info_dataclass():
    """Test the DeviceInfo dataclass."""
    device = DeviceInfo(
        entity_id="light.living_room",
        name="Living Room Light",
        state="on",
        attributes=["brightness: 80%", "color: blue"],
        area_id="living_room",
        area_name="Living Room"
    )

    assert device.entity_id == "light.living_room"
    assert device.name == "Living Room Light"
    assert device.state == "on"
    assert device.area_name == "Living Room"
    assert "brightness: 80%" in device.attributes
