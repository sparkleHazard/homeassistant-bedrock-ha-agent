"""Phase 5 Step 5.5: AC12 voice/text-stream contract — no diff markers in text_delta."""
from __future__ import annotations

import pytest

from custom_components.bedrock_ha_agent.conversation import (
    _split_proposal_for_stream,
)

pytest_plugins = ["pytest_homeassistant_custom_component"]


def test_split_proposal_for_stream_pending_approval():
    """Test AC12: split returns summary for speech, full dict for structured log."""
    tool_result = {
        "status": "pending_approval",
        "proposed_summary": "Would add automation 'Porch lights' that turns on light.porch at sunset",
        "proposed_diff": "--- before\n+++ after\n@@ -0,0 +1,5 @@\n+ id: porch_at_sunset\n+ alias: Porch lights\n- old line\n+ new line",
    }

    spoken_text, structured_payload = _split_proposal_for_stream(tool_result)

    # Spoken text should be ONLY the summary, no diff markers
    assert spoken_text == tool_result["proposed_summary"]
    assert "---" not in (spoken_text or "")
    assert "+++" not in (spoken_text or "")
    assert "@@" not in (spoken_text or "")
    assert "\n-" not in (spoken_text or "")
    assert "\n+" not in (spoken_text or "")

    # Structured payload should be the full tool result
    assert structured_payload == tool_result
    assert structured_payload["proposed_diff"] == tool_result["proposed_diff"]


def test_split_proposal_for_stream_non_pending_passthrough():
    """Test that non-pending results pass through unchanged."""
    tool_result = {"status": "success", "message": "Done", "object_id": "test.automation"}

    spoken_text, structured_payload = _split_proposal_for_stream(tool_result)

    assert spoken_text is None
    assert structured_payload == tool_result


def test_text_delta_never_contains_diff_markers():
    """Test AC12: verify _split_proposal_for_stream prevents diff markers in spoken text.

    This is the contract: when a config tool returns pending_approval,
    the spoken_text (which becomes text_delta payloads) MUST NOT contain
    diff markers (---, +++, @@, leading -/+). Only proposed_summary goes to speech.
    """
    # Simulate a realistic pending_approval response with large diff
    tool_result = {
        "status": "pending_approval",
        "proposal_id": "test_prop_123",
        "proposed_summary": "Would add automation 'Morning routine' with 3 actions",
        "proposed_diff": """--- automations.yaml (before)
+++ automations.yaml (after)
@@ -100,0 +100,12 @@
+- id: morning_routine
+  alias: Morning routine
+  trigger:
+    - platform: time
+      at: "06:00:00"
-  # old comment
+  # new comment
+  action:
+    - service: light.turn_on
+      target:
+        entity_id: light.bedroom""",
    }

    spoken_text, structured_payload = _split_proposal_for_stream(tool_result)

    # Verify spoken text is safe for TTS
    assert spoken_text is not None
    assert "---" not in spoken_text
    assert "+++" not in spoken_text
    assert "@@" not in spoken_text
    assert "- " not in spoken_text  # leading dash
    assert "+ " not in spoken_text  # leading plus
    assert "\n-" not in spoken_text
    assert "\n+" not in spoken_text

    # Verify summary content is present
    assert "Morning routine" in spoken_text
    assert "3 actions" in spoken_text

    # Verify structured payload still has everything
    assert structured_payload["proposed_diff"] == tool_result["proposed_diff"]
    assert "---" in structured_payload["proposed_diff"]


def test_empty_summary_returns_empty_string():
    """Test edge case: missing or empty proposed_summary."""
    tool_result = {
        "status": "pending_approval",
        "proposed_diff": "some diff",
    }

    spoken_text, structured_payload = _split_proposal_for_stream(tool_result)

    assert spoken_text == ""
    assert structured_payload == tool_result
