"""Global provider cost governance: kill switch, daily caps, day rollover."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import ProviderQuotaError
from app.services.cost_governor import CostGovernor


async def test_kill_switch_blocks_all_calls() -> None:
    governor = CostGovernor(kill_switch=True)
    with pytest.raises(ProviderQuotaError, match="kill switch"):
        await governor.reserve(estimated_tokens=1)


async def test_unlimited_by_default() -> None:
    governor = CostGovernor()
    for _ in range(50):
        await governor.reserve(estimated_tokens=10_000)


async def test_request_cap_is_enforced() -> None:
    governor = CostGovernor(max_requests_per_day=2)
    await governor.reserve(estimated_tokens=1)
    await governor.reserve(estimated_tokens=1)
    with pytest.raises(ProviderQuotaError, match="request budget"):
        await governor.reserve(estimated_tokens=1)


async def test_token_cap_is_enforced() -> None:
    governor = CostGovernor(max_tokens_per_day=100)
    await governor.reserve(estimated_tokens=60)
    with pytest.raises(ProviderQuotaError, match="token budget"):
        await governor.reserve(estimated_tokens=60)
    # A smaller call that still fits is allowed.
    await governor.reserve(estimated_tokens=40)


async def test_daily_counters_reset_across_utc_day() -> None:
    now = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)

    def clock() -> datetime:
        return now

    governor = CostGovernor(max_requests_per_day=1, clock=clock)
    await governor.reserve(estimated_tokens=1)
    with pytest.raises(ProviderQuotaError):
        await governor.reserve(estimated_tokens=1)

    now = now + timedelta(days=1)
    # New UTC day: budget is available again.
    await governor.reserve(estimated_tokens=1)


async def test_snapshot_reports_usage() -> None:
    governor = CostGovernor(max_requests_per_day=5, max_tokens_per_day=1000)
    await governor.reserve(estimated_tokens=100)
    snapshot = await governor.snapshot()
    assert snapshot["requests_used"] == 1
    assert snapshot["tokens_used"] == 100
    assert snapshot["max_requests_per_day"] == 5
    assert snapshot["max_tokens_per_day"] == 1000
    assert snapshot["kill_switch"] is False
