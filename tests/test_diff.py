"""Tests for diff rendering helpers."""

from __future__ import annotations

import pytest

from custom_components.bedrock_ha_agent.config_tools.diff import (
    _assert_tts_safe,
    is_tts_safe,
    render_spoken_summary,
    render_unified_diff,
)


class TestUnifiedDiff:
    """Test unified diff rendering."""

    def test_unified_diff_addition_only(self) -> None:
        """Pure addition shows + lines."""
        before = None
        after = {"alias": "X", "trigger": []}
        diff = render_unified_diff(before, after)
        assert diff
        assert "--- before" in diff
        assert "+++ after" in diff
        assert "+alias: X" in diff

    def test_unified_diff_deletion_only(self) -> None:
        """Pure deletion shows - lines."""
        before = {"alias": "X", "trigger": []}
        after = None
        diff = render_unified_diff(before, after)
        assert diff
        assert "--- before" in diff
        assert "+++ after" in diff
        assert "-alias: X" in diff

    def test_unified_diff_identical_returns_empty(self) -> None:
        """Identical before/after returns empty string."""
        obj = {"alias": "X", "trigger": []}
        diff = render_unified_diff(obj, obj)
        assert diff == ""

    def test_unified_diff_modification(self) -> None:
        """Modified value shows - and + lines."""
        before = {"alias": "X"}
        after = {"alias": "Y"}
        diff = render_unified_diff(before, after)
        assert diff
        assert "-alias: X" in diff
        assert "+alias: Y" in diff

    def test_yaml_determinism(self) -> None:
        """Dicts with same keys in different order produce identical diffs."""
        dict1 = {"z": 1, "a": 2, "m": 3}
        dict2 = {"a": 2, "z": 1, "m": 3}
        diff1 = render_unified_diff(None, dict1)
        diff2 = render_unified_diff(None, dict2)
        assert diff1 == diff2


class TestSpokenSummary:
    """Test TTS-safe spoken summary rendering."""

    def test_spoken_summary_basic(self) -> None:
        """Basic summary with verb and noun phrase."""
        summary = render_spoken_summary("Would add", "the automation 'Porch'")
        assert summary.startswith("Would add")
        assert "Porch" in summary
        assert len(summary) <= 200

    def test_spoken_summary_with_detail(self) -> None:
        """Summary with optional detail."""
        summary = render_spoken_summary(
            "Would rename", "the area 'Living Room'", detail="to 'Family Room'"
        )
        assert summary.startswith("Would rename")
        assert "Living Room" in summary
        assert "Family Room" in summary
        assert len(summary) <= 200

    def test_spoken_summary_truncation(self) -> None:
        """Long detail is truncated with ellipsis."""
        long_detail = "x" * 400
        summary = render_spoken_summary("Would add", "the automation", detail=long_detail)
        assert len(summary) <= 200
        assert summary.endswith("…")

    def test_spoken_summary_rejects_diff_markers(self) -> None:
        """Diff markers in text raise ValueError."""
        with pytest.raises(ValueError, match="diff marker"):
            _assert_tts_safe("--- before\n+++ after", 200)

    def test_spoken_summary_rejects_newline_plus(self) -> None:
        """Newline-then-plus raises ValueError."""
        with pytest.raises(ValueError, match="newline-then"):
            _assert_tts_safe("ok\n+something", 200)

    def test_spoken_summary_rejects_newline_minus(self) -> None:
        """Newline-then-minus raises ValueError."""
        with pytest.raises(ValueError, match="newline-then"):
            _assert_tts_safe("ok\n-something", 200)

    def test_spoken_summary_accepts_normal_text(self) -> None:
        """Normal text passes TTS safety check."""
        assert is_tts_safe("Would rename the area to 'Family Room'")

    def test_spoken_summary_empty_verb_raises(self) -> None:
        """Empty verb raises ValueError."""
        with pytest.raises(ValueError, match="verb is required"):
            render_spoken_summary("", "the automation")

    def test_spoken_summary_empty_noun_raises(self) -> None:
        """Empty noun phrase raises ValueError."""
        with pytest.raises(ValueError, match="noun_phrase is required"):
            render_spoken_summary("Would add", "")

    def test_is_tts_safe_at_boundary(self) -> None:
        """Text at exactly max_length is accepted, over limit is rejected."""
        text_200 = "x" * 200
        text_201 = "x" * 201
        assert is_tts_safe(text_200, max_length=200)
        assert not is_tts_safe(text_201, max_length=200)

    def test_spoken_summary_rejects_triple_minus(self) -> None:
        """Triple-minus marker is rejected."""
        with pytest.raises(ValueError, match="diff marker"):
            _assert_tts_safe("--- something", 200)

    def test_spoken_summary_rejects_triple_plus(self) -> None:
        """Triple-plus marker is rejected."""
        with pytest.raises(ValueError, match="diff marker"):
            _assert_tts_safe("+++ something", 200)

    def test_spoken_summary_rejects_at_marker(self) -> None:
        """@@ marker is rejected."""
        with pytest.raises(ValueError, match="diff marker"):
            _assert_tts_safe("@@ -1,3 +1,3 @@", 200)

    def test_spoken_summary_whitespace_trimming(self) -> None:
        """Verb and noun are trimmed of surrounding whitespace."""
        summary = render_spoken_summary("  Would add  ", "  the automation  ")
        assert summary == "Would add the automation"

    def test_spoken_summary_truncation_preserves_core(self) -> None:
        """When truncating, core verb+noun is never cut."""
        verb = "Would add"
        noun = "the automation 'X'"
        detail = "y" * 400
        summary = render_spoken_summary(verb, noun, detail=detail)
        assert summary.startswith(verb)
        assert noun in summary
        assert len(summary) <= 200
