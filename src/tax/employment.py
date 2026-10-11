"""Employment taxes: PAYE, NSSF and Local Service Tax, plus the payroll pipeline.

Order of deductions used by :class:`PayrollPipeline` (justified in the notebook):

    1. Gross      = basic pay + taxable allowances
    2. LST        = Local Service Tax instalment (only if enabled and in a deduction month)
    3. Chargeable = Gross - LST          (LST is allowed as a deduction before PAYE)
    4. PAYE       = progressive schedule applied to Chargeable
    5. NSSF       = 5% of Gross          (NOT deductible for PAYE, so it is based on Gross)
    6. Net pay    = Gross - LST - PAYE - NSSF
    Employer also pays NSSF of 10% of Gross on top; it is a cost, not a deduction from pay.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from src.tax.core import LineItem, Residency, Tax, TaxContext, TaxResult
from src.tax.errors import InvalidIncomeError
from src.tax.money import Money
from src.tax.schedules import ScheduleRegistry, default_registry


# ---------------------------------------------------------------------------
# PAYE
# ---------------------------------------------------------------------------
class PAYE(Tax):
    """Pay As You Earn: progressive income tax on monthly employment income.

    Resident and non-resident employees use different schedules; which one applies, and
    which version of it, is looked up in the registry from ``ctx.residency`` and
    ``ctx.on_date``. The class itself contains no rates.

    Args:
        registry: Where schedules are looked up. Defaults to the built-in Uganda schedules.
    """

    name = "PAYE"

    def __init__(self, registry: Optional[ScheduleRegistry] = None) -> None:
        self.registry = registry or default_registry()

    def chargeable_income(self, ctx: TaxContext) -> Money:
        """Gross pay + allowances - deductions allowed before PAYE."""
        gross = ctx.total_employment_income
        if ctx.pre_tax_deductions > gross:
            raise InvalidIncomeError(
                f"Pre-tax deductions ({ctx.pre_tax_deductions}) exceed employment income ({gross})."
            )
        return gross - ctx.pre_tax_deductions

    def calculate(self, ctx: TaxContext) -> TaxResult:
        chargeable = self.chargeable_income(ctx)
        schedule = self.registry.find(ctx.residency, ctx.on_date)  # may raise NoScheduleForDateError
        amount, lines = schedule.tax_on(chargeable)
        return TaxResult(self.name, amount, chargeable, lines, basis=f"{schedule.name}. {schedule.source}")


# ---------------------------------------------------------------------------
# NSSF
# ---------------------------------------------------------------------------
class NSSF(Tax):
    """National Social Security Fund contribution.

    The employee pays 5 % of gross pay and the employer adds 10 %. ``calculate`` returns
    the EMPLOYEE share (the amount deducted from pay); use :meth:`employer_contribution`
    for the employer's share.
    """

    name = "NSSF (employee 5%)"

    def __init__(self, employee_rate: Decimal = Decimal("0.05"), employer_rate: Decimal = Decimal("0.10")) -> None:
        for rate in (employee_rate, employer_rate):
            if not isinstance(rate, Decimal) or not Decimal("0") <= rate <= Decimal("1"):
                raise ValueError("NSSF rates must be Decimals between 0 and 1.")
        self.employee_rate = employee_rate
        self.employer_rate = employer_rate

    def calculate(self, ctx: TaxContext) -> TaxResult:
        gross = ctx.total_employment_income
        amount = gross * self.employee_rate
        line = LineItem(f"{self.employee_rate:.0%} of gross {gross.amount:,}", amount)
        return TaxResult(self.name, amount, gross, (line,), basis="NSSF Act: employee 5%, employer 10% of gross")

    def employer_contribution(self, ctx: TaxContext) -> Money:
        """The employer's 10 %: an extra cost to the employer, not taken from the employee."""
        return ctx.total_employment_income * self.employer_rate


# ---------------------------------------------------------------------------
# Local Service Tax
# ---------------------------------------------------------------------------
# (monthly income must EXCEED this, annual LST). Local Governments (Amendment) (No.2) Act 2008.
LST_BANDS: Tuple[Tuple[Decimal, Decimal], ...] = tuple(
    (Decimal(lower), Decimal(annual))
    for lower, annual in [
        ("100000", "5000"), ("200000", "10000"), ("300000", "20000"), ("400000", "30000"),
        ("500000", "40000"), ("600000", "60000"), ("700000", "70000"), ("800000", "80000"),
        ("900000", "90000"), ("1000000", "100000"),
    ]
)


class LocalServiceTax(Tax):
    """Local Service Tax: a fixed annual amount set by the employee's monthly income bracket.

    It is collected by the employer in equal instalments in the first four months of the
    financial year (July to October), so in other months the deduction is zero. Everything
    about it is configurable, because local governments and employers apply it differently.

    Args:
        enabled: Switch LST off entirely (the brief calls it optional).
        instalments: Number of equal instalments the annual amount is split into.
        months: Calendar months (1-12) in which an instalment is deducted.
        bands: (income-above, annual-amount) pairs in ascending order.
    """

    name = "Local Service Tax"

    def __init__(
        self,
        enabled: bool = True,
        instalments: int = 4,
        months: Sequence[int] = (7, 8, 9, 10),
        bands: Sequence[Tuple[Decimal, Decimal]] = LST_BANDS,
    ) -> None:
        if instalments < 1:
            raise ValueError("instalments must be at least 1.")
        if not all(1 <= m <= 12 for m in months):
            raise ValueError("months must be calendar months 1-12.")
        self.enabled = enabled
        self.instalments = instalments
        self.months = tuple(months)
        self.bands = tuple(bands)

    def annual_amount(self, monthly_income: Money) -> Money:
        """Annual LST for a monthly income: the amount of the highest bracket exceeded."""
        annual = Decimal("0")
        for lower, amount in self.bands:
            if monthly_income.amount > lower:
                annual = amount
        return Money(annual)

    def calculate(self, ctx: TaxContext) -> TaxResult:
        gross = ctx.total_employment_income
        annual = self.annual_amount(gross)
        basis = "Local Governments (Amendment) (No.2) Act 2008; KCCA Local Service Tax FAQs"
        if not self.enabled:
            return TaxResult(self.name, Money.zero(), gross, (LineItem("LST disabled", Money.zero()),), basis)
        if ctx.on_date.month not in self.months:
            line = LineItem(f"No instalment due in month {ctx.on_date.month} (annual {annual.amount:,})", Money.zero())
            return TaxResult(self.name, Money.zero(), gross, (line,), basis)
        instalment = Money(annual.amount / self.instalments)
        line = LineItem(f"Annual {annual.amount:,} / {self.instalments} instalments", instalment)
        return TaxResult(self.name, instalment, gross, (line,), basis)


# ---------------------------------------------------------------------------
# Payroll pipeline
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Payslip:
    """Everything on one employee's payslip for one month."""

    on_date: dt.date
    residency: Residency
    gross: Money
    lst: TaxResult
    paye: TaxResult
    nssf: TaxResult
    employer_nssf: Money

    @property
    def chargeable_income(self) -> Money:
        return self.paye.base

    @property
    def total_deductions(self) -> Money:
        return self.lst.amount + self.paye.amount + self.nssf.amount

    @property
    def net_pay(self) -> Money:
        return self.gross - self.total_deductions

    @property
    def employer_cost(self) -> Money:
        """What the job costs the employer: gross pay plus the employer's NSSF."""
        return self.gross + self.employer_nssf

    def as_rows(self) -> Tuple[Tuple[str, Money], ...]:
        """(label, amount) rows in the order the deductions are applied."""
        return (
            ("Gross pay (basic + allowances)", self.gross),
            ("1. Local Service Tax", self.lst.amount),
            ("   Chargeable income (gross - LST)", self.chargeable_income),
            ("2. PAYE", self.paye.amount),
            ("3. NSSF employee 5% (on gross)", self.nssf.amount),
            ("Total deductions", self.total_deductions),
            ("NET PAY", self.net_pay),
            ("Employer NSSF 10% (extra cost)", self.employer_nssf),
            ("Total cost to employer", self.employer_cost),
        )


class PayrollPipeline:
    """Runs LST -> PAYE -> NSSF in the documented order and returns a :class:`Payslip`.

    Composition, not inheritance: the pipeline *has* three Tax objects and can be given
    different ones (e.g. ``LocalServiceTax(enabled=False)`` or an NSSF with other rates).
    """

    def __init__(
        self,
        paye: Optional[PAYE] = None,
        nssf: Optional[NSSF] = None,
        lst: Optional[LocalServiceTax] = None,
    ) -> None:
        self.paye = paye or PAYE()
        self.nssf = nssf or NSSF()
        self.lst = lst or LocalServiceTax()

    def run(
        self,
        gross_pay: Money,
        on_date: dt.date,
        allowances: Optional[Money] = None,
        residency: Residency = Residency.RESIDENT,
    ) -> Payslip:
        base_ctx = TaxContext(
            on_date=on_date,
            residency=residency,
            gross_pay=gross_pay,
            allowances=allowances if allowances is not None else Money.zero(),
        )
        lst = self.lst.calculate(base_ctx)                                   # step 2
        paye_ctx = dataclasses.replace(base_ctx, pre_tax_deductions=lst.amount)  # step 3
        paye = self.paye.calculate(paye_ctx)                                 # step 4
        nssf = self.nssf.calculate(base_ctx)                                 # step 5 (on gross)
        return Payslip(
            on_date=on_date,
            residency=residency,
            gross=base_ctx.total_employment_income,
            lst=lst,
            paye=paye,
            nssf=nssf,
            employer_nssf=self.nssf.employer_contribution(base_ctx),
        )
