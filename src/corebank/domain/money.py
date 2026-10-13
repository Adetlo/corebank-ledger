"""Money value object.

Financial amounts are **never** represented with binary floating point. The
``Money`` type wraps :class:`decimal.Decimal` and enforces the minor-unit
precision of each supported currency (``GBP`` has 2 decimal places, ``JPY``
has 0, and so on), see :data:`CURRENCIES`.

Design notes
------------
* ``Money`` is immutable (frozen dataclass) and hashable.
* Arithmetic is only defined between amounts of the same currency; mixing
  currencies raises :class:`CurrencyMismatchError` rather than silently
  producing nonsense.
* Amounts are stored *quantized* to the currency's minor unit, so ``"10.1"``
  GBP becomes ``Decimal("10.10")``. An amount with *more* precision than the
  currency allows (``"10.001"`` GBP) is rejected rather than rounded: rounding
  is a business decision that must be made explicitly by the caller.
* Construction from ``float`` is rejected outright.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Final

from corebank.domain.exceptions import (
    CurrencyMismatchError,
    InvalidAmountError,
    UnsupportedCurrencyError,
)

#: Supported ISO 4217 currency codes mapped to their number of minor-unit digits.
CURRENCIES: Final[dict[str, int]] = {
    "GBP": 2,
    "USD": 2,
    "EUR": 2,
    "JPY": 0,
    "CHF": 2,
    "SGD": 2,
    "AUD": 2,
}

#: Upper bound on absolute amounts. Matches the NUMERIC(19, 4) column type.
MAX_ABS_AMOUNT: Final[Decimal] = Decimal("999999999999999")


def validate_currency(currency: str) -> str:
    """Return the normalised (upper-case) currency code or raise."""
    if not isinstance(currency, str):
        raise UnsupportedCurrencyError(currency=str(currency))
    code = currency.strip().upper()
    if code not in CURRENCIES:
        raise UnsupportedCurrencyError(
            f"Currency '{currency}' is not supported. Supported: {', '.join(CURRENCIES)}.",
            currency=currency,
        )
    return code


def minor_units(currency: str) -> int:
    """Number of decimal places for ``currency`` (e.g. 2 for GBP, 0 for JPY)."""
    return CURRENCIES[validate_currency(currency)]


def quantum(currency: str) -> Decimal:
    """Smallest representable amount for ``currency`` (``0.01`` for GBP)."""
    return Decimal(1).scaleb(-minor_units(currency))


def to_decimal(value: Decimal | int | str) -> Decimal:
    """Convert a safe input type to ``Decimal``.

    ``float`` is deliberately **not** accepted: ``Decimal(0.1)`` is
    ``0.1000000000000000055511151231257827...``.
    """
    if isinstance(value, bool | float):  # bool is an int subclass
        raise InvalidAmountError(
            "Amounts must be provided as Decimal, int or str, never float.",
            value=repr(value),
        )
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except (InvalidOperation, ValueError) as exc:
            raise InvalidAmountError(f"'{value}' is not a valid decimal amount.") from exc
    else:
        raise InvalidAmountError(value=repr(value))
    if not dec.is_finite():
        raise InvalidAmountError("Amount must be a finite number.", value=str(dec))
    return dec


@dataclass(frozen=True, slots=True, order=False)
class Money:
    """An immutable amount in a single currency, quantized to its minor unit."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        code = validate_currency(self.currency)
        dec = to_decimal(self.amount)
        q = quantum(code)
        quantized = dec.quantize(q, rounding=ROUND_HALF_EVEN)
        if quantized != dec:
            raise InvalidAmountError(
                f"Amount {dec} has more precision than {code} allows ({CURRENCIES[code]} dp).",
                amount=str(dec),
                currency=code,
            )
        if abs(quantized) > MAX_ABS_AMOUNT:
            raise InvalidAmountError("Amount exceeds the maximum supported magnitude.")
        # Bypass frozen semantics to store the normalised values.
        object.__setattr__(self, "amount", quantized)
        object.__setattr__(self, "currency", code)

    # ----- constructors -----------------------------------------------------
    @classmethod
    def of(cls, amount: Decimal | int | str, currency: str) -> Money:
        """Build a ``Money`` from a safe scalar type."""
        return cls(to_decimal(amount), currency)

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal(0), currency)

    # ----- predicates -------------------------------------------------------
    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    # ----- arithmetic -------------------------------------------------------
    def _check_same_currency(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError("Money can only be combined with Money.")
        if other.currency != self.currency:
            raise CurrencyMismatchError(
                f"Cannot combine {self.currency} with {other.currency}.",
                left=self.currency,
                right=other.currency,
            )

    def __add__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._check_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._check_same_currency(other)
        return self.amount >= other.amount

    # ----- presentation -----------------------------------------------------
    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    def as_string(self) -> str:
        """Canonical string form of the amount, e.g. ``"1000.00"`` or ``"100"``."""
        return format(self.amount, "f")


def sum_money(items: list[Money] | tuple[Money, ...], currency: str) -> Money:
    """Sum a sequence of ``Money`` in ``currency``; empty sequences sum to zero."""
    total = Money.zero(currency)
    for item in items:
        total = total + item
    return total
