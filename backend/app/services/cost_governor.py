"""Global provider cost governance.

A single, fail-closed gate in front of billable generative-provider calls. It
enforces an operator kill switch and per-day request/token budgets so a runaway
loop, a retry storm, or a compromised caller cannot silently spend the Azure
OpenAI budget. Counters are process-local and reset each UTC day; a multi-instance
production deployment must replace the backing store with a shared one (Redis or a
database counter) without changing this interface.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime

from app.core.config import Settings
from app.core.exceptions import ProviderQuotaError


class CostGovernor:
    def __init__(
        self,
        *,
        kill_switch: bool = False,
        max_requests_per_day: int = 0,
        max_tokens_per_day: int = 0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._kill_switch = kill_switch
        self._max_requests = max_requests_per_day
        self._max_tokens = max_tokens_per_day
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()
        self._day: date | None = None
        self._requests = 0
        self._tokens = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> CostGovernor:
        return cls(
            kill_switch=settings.provider_kill_switch,
            max_requests_per_day=settings.provider_max_requests_per_day,
            max_tokens_per_day=settings.provider_max_tokens_per_day,
        )

    def _roll_day(self) -> None:
        today = self._clock().date()
        if today != self._day:
            self._day = today
            self._requests = 0
            self._tokens = 0

    async def reserve(self, *, estimated_tokens: int) -> None:
        """Account for one upcoming provider call, or fail closed if it exceeds policy.

        Reservation is conservative: the estimate is counted before the call so a
        burst cannot slip past the budget between reservation and completion.
        """
        estimated = max(0, estimated_tokens)
        async with self._lock:
            self._roll_day()
            if self._kill_switch:
                raise ProviderQuotaError(
                    "Generative provider processing is disabled by the operator kill switch."
                )
            if self._max_requests and self._requests + 1 > self._max_requests:
                raise ProviderQuotaError(
                    "The daily provider request budget has been reached."
                )
            if self._max_tokens and self._tokens + estimated > self._max_tokens:
                raise ProviderQuotaError(
                    "The daily provider token budget has been reached."
                )
            self._requests += 1
            self._tokens += estimated

    async def snapshot(self) -> dict[str, int | bool | None]:
        async with self._lock:
            self._roll_day()
            return {
                "kill_switch": self._kill_switch,
                "requests_used": self._requests,
                "tokens_used": self._tokens,
                "max_requests_per_day": self._max_requests or None,
                "max_tokens_per_day": self._max_tokens or None,
            }
