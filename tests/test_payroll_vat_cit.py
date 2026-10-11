"""Tests for the payroll pipeline, NSSF, Local Service Tax, VAT and corporate income tax."""
import datetime as dt
from decimal import Decimal

import pytest

from src.tax import (
    NSSF,
    VAT,
    CorporateIncomeTax,
    InvalidIncomeError,
    InvalidInvoiceError,
    Invoice,
    InvoiceKind,
    LocalServiceTax,
    Money,
    PayrollPipeline,
    Residency,
    SupplyType,
    Tax,
    TaxContext,
    WithholdingTax,
)

SEPT = dt.date(2026, 9, 15)   # an LST month
JAN = dt.date(2027, 1, 15)    # not an LST month


# --- payroll -----------------------------------------------------------------
def test_payslip_hand_calculation_in_lst_month():
    slip = PayrollPipeline().run(Money(2_500_000), SEPT, allowances=Money(500_000))
    assert slip.gross == Money(3_000_000)
    assert slip.lst.amount == Money(25_000)                 # 100,000 a year / 4
    assert slip.chargeable_income == Money(2_975_000)       # LST comes off before PAYE
    assert slip.paye.amount == Money(780_750)               # 33,750 + 30% x 2,490,000
    assert slip.nssf.amount == Money(150_000)               # 5% of GROSS, not of chargeable
    assert slip.net_pay == Money(2_044_250)
    assert slip.employer_nssf == Money(300_000)
    assert slip.employer_cost == Money(3_300_000)


def test_no_lst_outside_july_to_october():
    slip = PayrollPipeline().run(Money(3_000_000), JAN)
    assert slip.lst.amount == Money(0)
    assert slip.paye.amount == Money(788_250)               # 33,750 + 30% x 2,515,000
    assert slip.net_pay == Money(3_000_000 - 788_250 - 150_000)


def test_lst_can_be_switched_off():
    slip = PayrollPipeline(lst=LocalServiceTax(enabled=False)).run(Money(3_000_000), SEPT)
    assert slip.lst.amount == Money(0)


def test_non_resident_payslip_uses_non_resident_schedule():
    slip = PayrollPipeline(lst=LocalServiceTax(enabled=False)).run(
        Money(3_000_000), SEPT, residency=Residency.NON_RESIDENT
    )
    assert slip.paye.amount == Money(825_500)               # 48,500 + 30% x 2,590,000


@pytest.mark.parametrize(
    "monthly, annual",
    [(100_000, 0), (100_001, 5_000), (300_000, 10_000), (300_001, 20_000),
     (650_000, 60_000), (1_000_000, 90_000), (1_000_001, 100_000)],
)
def test_lst_brackets(monthly, annual):
    assert LocalServiceTax().annual_amount(Money(monthly)) == Money(annual)


def test_zero_pay_gives_zero_everything():
    slip = PayrollPipeline().run(Money(0), SEPT)
    assert slip.net_pay == Money(0) and slip.total_deductions == Money(0)


def test_nssf_rates_and_validation():
    ctx = TaxContext(on_date=SEPT, gross_pay=Money(1_000_000))
    assert NSSF().calculate(ctx).amount == Money(50_000)
    assert NSSF().employer_contribution(ctx) == Money(100_000)
    with pytest.raises(ValueError):
        NSSF(employee_rate=Decimal("1.5"))


# --- VAT -----------------------------------------------------------------------
def inv(number, kind, supply, amount):
    return Invoice(number, kind, supply, Money(amount))


def vat_for(*invoices):
    return VAT().summarise(invoices)


def test_vat_standard_only():
    s = vat_for(
        inv("S1", InvoiceKind.SALE, SupplyType.STANDARD, 10_000_000),
        inv("P1", InvoiceKind.PURCHASE, SupplyType.STANDARD, 4_000_000),
    )
    assert s.output_vat == Money(1_800_000)
    assert s.input_vat == Money(720_000)
    assert s.net_vat_payable == Money(1_080_000)


def test_zero_rated_sales_charge_no_vat_but_keep_full_input_credit():
    s = vat_for(
        inv("S1", InvoiceKind.SALE, SupplyType.ZERO_RATED, 10_000_000),
        inv("P1", InvoiceKind.PURCHASE, SupplyType.STANDARD, 4_000_000),
    )
    assert s.output_vat == Money(0)
    assert s.recoverable_fraction == Decimal("1")
    assert s.net_vat_payable == Money(-720_000)             # a refund position


def test_exempt_sales_block_input_credit():
    s = vat_for(
        inv("S1", InvoiceKind.SALE, SupplyType.EXEMPT, 10_000_000),
        inv("P1", InvoiceKind.PURCHASE, SupplyType.STANDARD, 4_000_000),
    )
    assert s.output_vat == Money(0)
    assert s.claimable_input_vat == Money(0)
    assert s.net_vat_payable == Money(0)


def test_mixed_supplies_apportion_input_vat():
    s = vat_for(
        inv("S1", InvoiceKind.SALE, SupplyType.STANDARD, 10_000_000),
        inv("S2", InvoiceKind.SALE, SupplyType.ZERO_RATED, 4_000_000),
        inv("S3", InvoiceKind.SALE, SupplyType.EXEMPT, 6_000_000),
        inv("P1", InvoiceKind.PURCHASE, SupplyType.STANDARD, 5_000_000),
    )
    assert s.recoverable_fraction == Decimal("0.7")         # 14m taxable / 20m total
    assert s.claimable_input_vat == Money(630_000)          # 70% of 900,000
    assert s.net_vat_payable == Money(1_170_000)


def test_small_exempt_share_is_ignored_under_5_percent_rule():
    s = vat_for(
        inv("S1", InvoiceKind.SALE, SupplyType.STANDARD, 9_700_000),
        inv("S2", InvoiceKind.SALE, SupplyType.EXEMPT, 300_000),      # 3% exempt
        inv("P1", InvoiceKind.PURCHASE, SupplyType.STANDARD, 1_000_000),
    )
    assert s.recoverable_fraction == Decimal("1")


def test_vat_with_no_invoices_is_nil():
    assert VAT().calculate(TaxContext(on_date=SEPT)).amount == Money(0)


def test_bad_invoices_rejected():
    with pytest.raises(InvalidInvoiceError):
        Invoice("X", InvoiceKind.SALE, SupplyType.STANDARD, Money(-5))
    with pytest.raises(InvalidInvoiceError):
        Invoice("X", InvoiceKind.SALE, SupplyType.STANDARD, 1000)        # not Money
    with pytest.raises(InvalidInvoiceError):
        Invoice("X", "sale", SupplyType.STANDARD, Money(5))              # not an enum
    with pytest.raises(InvalidInvoiceError):
        VAT().calculate(TaxContext(on_date=SEPT, invoices=("not an invoice",)))


# --- corporate income tax ----------------------------------------------------------
def test_corporate_tax_hand_calculation():
    ctx = TaxContext(on_date=SEPT, revenue=Money(500_000_000), allowable_deductions=Money(380_000_000))
    result = CorporateIncomeTax().calculate(ctx)
    assert result.base == Money(120_000_000)
    assert result.amount == Money(36_000_000)


def test_corporate_loss_gives_zero_tax_not_negative_tax():
    ctx = TaxContext(on_date=SEPT, revenue=Money(100), allowable_deductions=Money(500))
    assert CorporateIncomeTax().calculate(ctx).amount == Money(0)


def test_corporate_tax_needs_revenue():
    with pytest.raises(InvalidIncomeError):
        CorporateIncomeTax().calculate(TaxContext(on_date=SEPT))


# --- design ---------------------------------------------------------------------------
def test_tax_is_abstract_and_all_taxes_share_the_interface():
    with pytest.raises(TypeError):
        Tax()                                                 # abstract: cannot be instantiated
    for tax in (NSSF(), LocalServiceTax(), VAT(), CorporateIncomeTax(), WithholdingTax()):
        assert isinstance(tax, Tax)
