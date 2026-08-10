"""The cost ledger and the provider rate limiter (M5).

Both exist because a study spends real money on somebody else's rate-limited
service, and both fail in the direction of doing less rather than more.

**The budget cap is checked before a trial starts, never after.** Checking after
turns the cap into a number the study exceeded by one trial; checking before
turns it into a number the study cannot exceed by design. What a cap cannot
promise is that the *last* trial is cheap — a trial already running is already
spending — so the guarantee is precisely "no trial starts once the cap is
reached", and that is what the test asserts.

**Cost comes from ADP, not from a local estimate.** Every completed trial's
spend is read back from ``GET /runs/{id}/stats`` in micro-dollars, the integer
unit ADP stores. A ledger that added up estimated prices would be a ledger that
disagrees with the invoice, and duva-bench's whole stance is that a number you
cannot re-derive from the system of record is not a number.

**An unpriced trial is unpriced, not free.** A run whose events carry no
``cost_micro_usd`` contributes nothing to the total and is counted separately.
Treating it as zero would make an unmetered provider look like a cheap one.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

MICRO = Decimal(1_000_000)


class BudgetExceeded(RuntimeError):
    """The cap is reached. No further trial may start."""


@dataclass
class CostLedger:
    """What a study has spent, in the unit ADP reports it in."""

    cap_usd: Decimal
    spent_micro_usd: int = 0
    priced_trials: int = 0
    # Trials whose runs reported no cost at all. Not zero-cost trials: trials
    # whose cost nobody recorded.
    unpriced_trials: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def spent_usd(self) -> Decimal:
        return Decimal(self.spent_micro_usd) / MICRO

    @property
    def remaining_usd(self) -> Decimal:
        return self.cap_usd - self.spent_usd

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.cap_usd

    def record(self, micro_usd: int | None) -> None:
        """Add one completed trial's spend, or note that it had none."""
        with self._lock:
            if micro_usd is None:
                self.unpriced_trials += 1
                return
            self.spent_micro_usd += int(micro_usd)
            self.priced_trials += 1

    def check(self) -> None:
        """Raise if a trial must not start. Called before every trial."""
        with self._lock:
            if self.spent_usd >= self.cap_usd:
                raise BudgetExceeded(
                    f"the study has spent ${self.spent_usd} of its ${self.cap_usd} cap "
                    f"across {self.priced_trials} priced trial(s)"
                    + (
                        f" (and {self.unpriced_trials} whose cost ADP did not report)"
                        if self.unpriced_trials
                        else ""
                    )
                    + ". No further trial will start."
                )

    def summary(self) -> dict[str, object]:
        return {
            "cap_usd": str(self.cap_usd),
            "spent_usd": str(self.spent_usd),
            "remaining_usd": str(self.remaining_usd),
            "priced_trials": self.priced_trials,
            # Reported, never folded into the total.
            "unpriced_trials": self.unpriced_trials,
        }


@dataclass
class ProviderLimiter:
    """Per-provider request pacing, in requests per minute.

    A trial is one request to a provider in the sense that matters here: it opens
    an agent session that runs for minutes. So the limiter spaces *trial starts*
    rather than trying to model the token bucket inside the provider, which
    duva-bench cannot see and should not guess at.

    ``clock`` and ``sleep`` are injected so the test suite can prove the spacing
    without spending the wall clock proving it.
    """

    limits: dict[str, int] = field(default_factory=dict)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def interval(self, provider: str) -> float:
        limit = self.limits.get(provider)
        # No limit configured means no pacing. That is the right default for a
        # local model and the wrong one for a paid API, which is why a study
        # that needs pacing says so in its spec rather than inheriting a guess.
        return 60.0 / limit if limit and limit > 0 else 0.0

    def acquire(self, provider: str) -> float:
        """Block until this provider may be called again. Returns the wait."""
        interval = self.interval(provider)
        if interval <= 0:
            return 0.0

        with self._lock:
            now = self.clock()
            earliest = self._last.get(provider, float("-inf")) + interval
            wait = max(0.0, earliest - now)
            # The slot is claimed while the lock is held, so two threads asking
            # at once get two different slots rather than the same one.
            self._last[provider] = now + wait

        if wait > 0:
            self.sleep(wait)
        return wait
