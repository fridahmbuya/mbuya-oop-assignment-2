"""Money: an immutable value object for Uganda shillings (UGX).

Design rules
    * Amounts are stored as ``decimal.Decimal``. ``float`` is rejected everywhere,
      because binary floats cannot represent most decimal fractions exactly
      (``0.1 + 0.2 != 0.3``).
    * UGX has no minor unit in everyday use, so a Money is always a WHOLE number of
      shillings.
    * Rounding rule: round half up to the nearest shilling (``ROUND_HALF_UP``): 0.5 goes
      up, 0.4 goes down. It is applied in exactly one place, :meth:`Money._quantise`.
    * Long calculations (e.g. a progressive tax over several bands) should be done on
      exact ``Decimal`` values and wrapped in Money once at the end, so rounding happens
      once, not once per step.

A "value object" is defined by its value, not its identity: ``Money(100) == Money(100)``,
it can be used as a dict key, and it can never be changed after creation.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import total_ordering
from typing import Union

from src.tax.errors import MoneyTypeError

Number = Union[int, str, Decimal]


@total_ordering
class Money:
    """A whole number of Uganda shillings.

    Args:
        amount: ``int``, ``str`` or ``Decimal``. A ``float`` raises :class:`MoneyTypeError`.
            A fractional Decimal/str is rounded half up to the nearest shilling.

    Examples:
        >>> Money(1000) + Money("250")
        Money('UGX 1,250')
        >>> Money(1025) * Decimal("0.18")      # 184.5 rounds half up
        Money('UGX 185')
    """

    __slots__ = ("_amount",)

    CURRENCY = "UGX"
    ROUNDING = ROUND_HALF_UP
    _UNIT = Decimal("1")  # smallest amount we keep: one shilling

    def __init__(self, amount: Number) -> None:
        object.__setattr__(self, "_amount", self._quantise(self._to_decimal(amount)))

    # -- construction helpers -------------------------------------------------
    @staticmethod
    def _to_decimal(value: Number) -> Decimal:
        """Convert int/str/Decimal to Decimal; refuse float, bool and anything else."""
        if isinstance(value, bool) or isinstance(value, float):
            raise MoneyTypeError(
                f"Money does not accept {type(value).__name__} ({value!r}). "
                "Use int, str or decimal.Decimal, e.g. Money('1500.50')."
            )
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, (int, str)):
            try:
                result = Decimal(value)
            except InvalidOperation:
                raise MoneyTypeError(f"{value!r} is not a valid amount.") from None
        else:
            raise MoneyTypeError(f"Cannot build Money from {type(value).__name__}.")
        if not result.is_finite():
            raise MoneyTypeError("Money must be a finite number.")
        return result

    @classmethod
    def _quantise(cls, value: Decimal) -> Decimal:
        """THE rounding rule: nearest whole shilling, halves rounded up."""
        return value.quantize(cls._UNIT, rounding=cls.ROUNDING)

    @classmethod
    def zero(cls) -> "Money":
        return cls(0)

    # -- read access ----------------------------------------------------------
    @property
    def amount(self) -> Decimal:
        """The amount as an exact Decimal (whole shillings)."""
        return self._amount

    def __setattr__(self, name: str, value: object) -> None:  # immutability
        raise AttributeError("Money is immutable.")

    # -- arithmetic -----------------------------------------------------------
    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self._amount + other._amount)

    def __radd__(self, other: object) -> "Money":
        # Lets sum([Money, Money, ...]) work: sum() starts with the int 0.
        if isinstance(other, int) and not isinstance(other, bool) and other == 0:
            return self
        return NotImplemented

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self._amount - other._amount)

    def __mul__(self, factor: Union[int, Decimal]) -> "Money":
        """Multiply by a pure number (a rate or a count); the result is rounded half up.

        Money x Money is meaningless (shillings squared) and float is unsafe, so both raise.
        """
        if isinstance(factor, Money):
            raise MoneyTypeError("Cannot multiply Money by Money.")
        if isinstance(factor, bool) or isinstance(factor, float):
            raise MoneyTypeError("Multiply Money by int or Decimal, never float.")
        if not isinstance(factor, (int, Decimal)):
            return NotImplemented
        return Money(self._amount * Decimal(factor))

    __rmul__ = __mul__

    def __neg__(self) -> "Money":
        return Money(-self._amount)

    def ratio(self, other: "Money") -> Decimal:
        """Exact ratio self / other as a Decimal (used for apportionment and effective rates)."""
        if not isinstance(other, Money):
            raise MoneyTypeError("ratio() needs another Money.")
        if other._amount == 0:
            raise ZeroDivisionError("Cannot take a ratio to zero shillings.")
        return self._amount / other._amount

    # -- comparison -----------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._amount == other._amount

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._amount < other._amount

    def __hash__(self) -> int:
        return hash((self.CURRENCY, self._amount))

    def __bool__(self) -> bool:
        return self._amount != 0

    def is_negative(self) -> bool:
        return self._amount < 0

    # -- display --------------------------------------------------------------
    def __repr__(self) -> str:
        return f"Money('{self}')"

    def __str__(self) -> str:
        return f"{self.CURRENCY} {self._amount:,}"

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)

