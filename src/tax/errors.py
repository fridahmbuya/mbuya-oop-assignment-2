"""Custom exception hierarchy for the tax engine.

Every problem the engine can detect is raised as a subclass of :class:`TaxError`, so a
caller can catch *all* tax problems with one ``except TaxError`` or a specific one with
``except InvalidIncomeError``. Nothing fails silently: a wrong input never produces a
plausible-looking number.

    TaxError
    ├── InvalidIncomeError        negative, missing or non-Money income/amounts
    ├── NoScheduleForDateError    no tax schedule is in force on the requested date
    ├── InvalidInvoiceError       a VAT invoice that cannot be processed
    └── MoneyTypeError            Money combined with an unsupported type such as float
"""

from __future__ import annotations


class TaxError(Exception):
    """Base class for every error raised by the tax engine."""


class InvalidIncomeError(TaxError, ValueError):
    """Income or another monetary input is missing, negative or of the wrong type.

    Also inherits from ``ValueError`` so generic code that expects a ``ValueError`` for bad
    arguments still works.
    """


class NoScheduleForDateError(TaxError, LookupError):
    """No rate schedule covers the requested date (e.g. a date before the oldest schedule)."""


class InvalidInvoiceError(TaxError, ValueError):
    """A VAT invoice has an invalid amount, kind or supply type."""


class MoneyTypeError(TaxError, TypeError):
    """Money was combined with an unsupported type (most importantly: ``float``)."""
