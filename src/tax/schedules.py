"""Progressive rate schedules and a date-aware registry of them.

Tax rates are DATA, not code. A schedule says "from this date, these bands apply". The
PAYE class asks the registry "which schedule was in force on 15 September 2026 for a
resident?" and applies whatever comes back. When Parliament changes the bands, a new
schedule is registered and no calculation code changes.

Schedules included (all amounts are MONTHLY, in UGX)

    Resident, 1 Jul 2012 - 30 Jun 2026    nil to 235,000; 10% to 335,000; 20% to 410,000; 30% above;
                                          plus 10% of the excess over 10,000,000
    Resident, from 1 Jul 2026             nil to 335,000; 20% to 410,000; 25% to 485,000; 30% above;
                                          plus 10% of the excess over 10,000,000
                                          (Income Tax (Amendment) Act, 2026 - the assignment baseline)
    Non-resident, from 1 Jul 2012         10% to 335,000; 20% to 410,000; 30% above;
                                          plus 10% of the excess over 10,000,000

See README.md ("Tax rates and sources") for the citations and the date they were checked.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from src.tax.core import LineItem, Residency
from src.tax.errors import InvalidIncomeError, NoScheduleForDateError
from src.tax.money import Money


@dataclass(frozen=True)
class Band:
    """One slice of income taxed at one marginal rate.

    Attributes:
        lower: Income above this amount falls in the band.
        upper: Top of the band, or ``None`` for "no upper limit".
        rate: Marginal rate as a Decimal fraction (``Decimal("0.20")`` = 20 %).
    """

    lower: Decimal
    upper: Optional[Decimal]
    rate: Decimal

    def __post_init__(self) -> None:
        if self.lower < 0 or (self.upper is not None and self.upper <= self.lower):
            raise ValueError(f"Invalid band limits: {self.lower} to {self.upper}.")
        if not Decimal("0") <= self.rate <= Decimal("1"):
            raise ValueError(f"Rate must be between 0 and 1, got {self.rate}.")

    def portion_of(self, income: Decimal) -> Decimal:
        """How much of ``income`` lies inside this band."""
        top = income if self.upper is None else min(income, self.upper)
        return max(Decimal("0"), top - self.lower)


@dataclass(frozen=True)
class ProgressiveSchedule:
    """A set of contiguous bands, an optional high-income surcharge, and validity dates.

    Attributes:
        name: Human-readable label used in results.
        effective_from: First day the schedule applies.
        effective_to: Last day it applies, or ``None`` if it is still in force.
        bands: Bands in ascending order, starting at 0 with no gaps.
        surcharge_threshold: Income above this pays ``surcharge_rate`` on the excess,
            in addition to the band tax (Uganda: 10 % above UGX 10,000,000 a month).
        surcharge_rate: The additional rate.
        source: Citation for the rates.
    """

    name: str
    effective_from: dt.date
    effective_to: Optional[dt.date]
    bands: Tuple[Band, ...]
    surcharge_threshold: Optional[Decimal] = None
    surcharge_rate: Decimal = Decimal("0")
    source: str = ""

    def __post_init__(self) -> None:
        if not self.bands or self.bands[0].lower != 0:
            raise ValueError("Bands must start at 0.")
        for previous, current in zip(self.bands, self.bands[1:]):
            if previous.upper != current.lower:
                raise ValueError("Bands must be contiguous (no gaps or overlaps).")
        if self.bands[-1].upper is not None:
            raise ValueError("The last band must be open-ended.")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to is before effective_from.")

    def covers(self, on_date: dt.date) -> bool:
        """True if the schedule is in force on ``on_date``."""
        return self.effective_from <= on_date and (
            self.effective_to is None or on_date <= self.effective_to
        )

    def tax_on(self, income: Money) -> Tuple[Money, Tuple[LineItem, ...]]:
        """Tax on a monthly chargeable income, with a line-by-line breakdown.

        The arithmetic is done on exact Decimals and rounded ONCE at the end, so the
        result does not depend on how many bands the income passes through.
        """
        if income.is_negative():
            raise InvalidIncomeError(f"Chargeable income cannot be negative ({income}).")
        amount = income.amount
        total = Decimal("0")
        lines: List[LineItem] = []
        for band in self.bands:
            portion = band.portion_of(amount)
            if portion == 0:
                continue
            tax = portion * band.rate
            total += tax
            upper = "and above" if band.upper is None else f"to {band.upper:,}"
            lines.append(
                LineItem(f"{band.rate:.0%} of {portion:,} (band {band.lower:,} {upper})", Money(tax))
            )
        if self.surcharge_threshold is not None and amount > self.surcharge_threshold:
            excess = amount - self.surcharge_threshold
            extra = excess * self.surcharge_rate
            total += extra
            lines.append(
                LineItem(
                    f"plus {self.surcharge_rate:.0%} of {excess:,} over {self.surcharge_threshold:,}",
                    Money(extra),
                )
            )
        return Money(total), tuple(lines)


class ScheduleRegistry:
    """Holds every known schedule and finds the one in force on a given date.

    Raises :class:`NoScheduleForDateError` instead of guessing when nothing matches.
    """

    def __init__(self) -> None:
        self._schedules: Dict[Residency, List[ProgressiveSchedule]] = {r: [] for r in Residency}

    def register(self, residency: Residency, schedule: ProgressiveSchedule) -> None:
        """Add a schedule; overlapping validity periods for the same residency are refused."""
        for existing in self._schedules[residency]:
            latest_start = max(existing.effective_from, schedule.effective_from)
            earliest_end = min(
                existing.effective_to or dt.date.max, schedule.effective_to or dt.date.max
            )
            if latest_start <= earliest_end:
                raise ValueError(f"'{schedule.name}' overlaps '{existing.name}'.")
        self._schedules[residency].append(schedule)
        self._schedules[residency].sort(key=lambda s: s.effective_from)

    def find(self, residency: Residency, on_date: dt.date) -> ProgressiveSchedule:
        """Return the schedule in force for ``residency`` on ``on_date``."""
        for schedule in self._schedules[residency]:
            if schedule.covers(on_date):
                return schedule
        known = ", ".join(
            f"{s.effective_from} to {s.effective_to or 'now'}" for s in self._schedules[residency]
        )
        raise NoScheduleForDateError(
            f"No {residency.value} PAYE schedule is in force on {on_date}. "
            f"Known periods: {known or 'none'}."
        )

    def all(self, residency: Residency) -> Tuple[ProgressiveSchedule, ...]:
        return tuple(self._schedules[residency])


# ---------------------------------------------------------------------------
# The schedules themselves
# ---------------------------------------------------------------------------
def _d(text: str) -> Decimal:
    return Decimal(text)


SURCHARGE_THRESHOLD = _d("10000000")
SURCHARGE_RATE = _d("0.10")

RESIDENT_2012 = ProgressiveSchedule(
    name="Resident individuals, monthly (1 Jul 2012 - 30 Jun 2026)",
    effective_from=dt.date(2012, 7, 1),
    effective_to=dt.date(2026, 6, 30),
    bands=(
        Band(_d("0"), _d("235000"), _d("0")),
        Band(_d("235000"), _d("335000"), _d("0.10")),
        Band(_d("335000"), _d("410000"), _d("0.20")),
        Band(_d("410000"), None, _d("0.30")),
    ),
    surcharge_threshold=SURCHARGE_THRESHOLD,
    surcharge_rate=SURCHARGE_RATE,
    source="URA, PAYE rates page (https://ura.go.ug/en/domestic-taxes/paye-rates/), read 7 Oct 2026",
)

RESIDENT_2026 = ProgressiveSchedule(
    name="Resident individuals, monthly (from 1 Jul 2026)",
    effective_from=dt.date(2026, 7, 1),
    effective_to=None,
    bands=(
        Band(_d("0"), _d("335000"), _d("0")),
        Band(_d("335000"), _d("410000"), _d("0.20")),
        Band(_d("410000"), _d("485000"), _d("0.25")),
        Band(_d("485000"), None, _d("0.30")),
    ),
    surcharge_threshold=SURCHARGE_THRESHOLD,
    surcharge_rate=SURCHARGE_RATE,
    source="Income Tax (Amendment) Act, 2026 (assented 20 Aug 2026, effective 1 Jul 2026); "
    "assignment baseline",
)

NON_RESIDENT_2012 = ProgressiveSchedule(
    name="Non-resident individuals, monthly (from 1 Jul 2012)",
    effective_from=dt.date(2012, 7, 1),
    effective_to=None,
    bands=(
        Band(_d("0"), _d("335000"), _d("0.10")),
        Band(_d("335000"), _d("410000"), _d("0.20")),
        Band(_d("410000"), None, _d("0.30")),
    ),
    surcharge_threshold=SURCHARGE_THRESHOLD,
    surcharge_rate=SURCHARGE_RATE,
    source="URA, PAYE rates page (https://ura.go.ug/en/domestic-taxes/paye-rates/), read 7 Oct 2026",
)


def default_registry() -> ScheduleRegistry:
    """A registry loaded with the three schedules above."""
    registry = ScheduleRegistry()
    registry.register(Residency.RESIDENT, RESIDENT_2012)
    registry.register(Residency.RESIDENT, RESIDENT_2026)
    registry.register(Residency.NON_RESIDENT, NON_RESIDENT_2012)
    return registry
