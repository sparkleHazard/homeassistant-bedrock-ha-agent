"""Track Bedrock token usage + estimated cost per config entry.

One ``UsageTracker`` lives on ``entry.runtime_data.usage`` and is updated
from ``BedrockClient.async_generate`` after every response. The ``sensor``
platform reads its counters.

Counters reset automatically when the UTC day rolls over, so
``sensor.*_tokens_today`` values track a rolling 24h-ish window anchored to
UTC midnight. ``total`` counters accumulate forever (until the integration is
reloaded).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

# Anthropic Bedrock pricing per 1M tokens (USD), as of 2026-04 in us-* regions.
# Keyed by substring of the model id, longest/most-specific first.
# cache_read is typically 10% of input; cache_write is typically 125% of input.
@dataclass(frozen=True)
class ModelPricing:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float


_PRICING: tuple[tuple[str, ModelPricing], ...] = (
    (
        "claude-sonnet-4-5",
        ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0,
                     cache_read_per_mtok=0.30, cache_write_per_mtok=3.75),
    ),
    (
        "claude-haiku-4-5",
        ModelPricing(input_per_mtok=1.0, output_per_mtok=5.0,
                     cache_read_per_mtok=0.10, cache_write_per_mtok=1.25),
    ),
    (
        "claude-3-5-sonnet",
        ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0,
                     cache_read_per_mtok=0.30, cache_write_per_mtok=3.75),
    ),
    (
        "claude-3-5-haiku",
        ModelPricing(input_per_mtok=0.80, output_per_mtok=4.0,
                     cache_read_per_mtok=0.08, cache_write_per_mtok=1.0),
    ),
    (
        "claude-3-opus",
        ModelPricing(input_per_mtok=15.0, output_per_mtok=75.0,
                     cache_read_per_mtok=1.50, cache_write_per_mtok=18.75),
    ),
    (
        "claude-3-sonnet",
        ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0,
                     cache_read_per_mtok=0.30, cache_write_per_mtok=3.75),
    ),
    (
        "claude-3-haiku",
        ModelPricing(input_per_mtok=0.25, output_per_mtok=1.25,
                     cache_read_per_mtok=0.03, cache_write_per_mtok=0.30),
    ),
)


def _lookup_pricing(model_id: str | None) -> ModelPricing | None:
    if not model_id:
        return None
    for prefix, pricing in _PRICING:
        if prefix in model_id:
            return pricing
    return None


@dataclass
class UsageCounters:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class UsageTracker:
    """Per-entry running total of Bedrock token usage + cost + health."""

    today: UsageCounters = field(default_factory=UsageCounters)
    total: UsageCounters = field(default_factory=UsageCounters)
    last_reset_day: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    last_error: str | None = None
    last_error_at: datetime | None = None
    last_success_at: datetime | None = None
    _listeners: list[Callable[[], None]] = field(default_factory=list)

    def record_error(self, message: str) -> None:
        """Record a Bedrock failure and fire listeners."""
        self.last_error = message
        self.last_error_at = datetime.now(timezone.utc)
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        """Register a callback fired after each ``record`` call; returns unsubscribe."""
        self._listeners.append(cb)

        def _unsub() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _unsub

    def _maybe_roll_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset_day:
            self.today = UsageCounters()
            self.last_reset_day = today

    def record(self, model_id: str | None, usage: dict | None) -> None:
        """Fold one Bedrock ``usage`` dict into the counters.

        ``usage`` comes straight off the Bedrock response body; missing keys
        and ``None`` values are tolerated so older or error responses can be
        passed through safely.
        """
        if not usage:
            return

        self._maybe_roll_day()

        input_t = int(usage.get("input_tokens") or 0)
        output_t = int(usage.get("output_tokens") or 0)
        cache_read_t = int(usage.get("cache_read_input_tokens") or 0)
        cache_write_t = int(usage.get("cache_creation_input_tokens") or 0)

        pricing = _lookup_pricing(model_id)
        delta_cost = 0.0
        if pricing is not None:
            delta_cost = (
                input_t * pricing.input_per_mtok
                + output_t * pricing.output_per_mtok
                + cache_read_t * pricing.cache_read_per_mtok
                + cache_write_t * pricing.cache_write_per_mtok
            ) / 1_000_000

        for bucket in (self.today, self.total):
            bucket.input_tokens += input_t
            bucket.output_tokens += output_t
            bucket.cache_read_tokens += cache_read_t
            bucket.cache_write_tokens += cache_write_t
            bucket.cost_usd += delta_cost

        self.last_success_at = datetime.now(timezone.utc)

        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001 — listener bugs must not break the tracker
                pass
