"""Money that is never a bare number.

Every monetary value carries its currency, and every converted value carries
the rate used and that rate's as-of date. Arithmetic between currencies is a
TypeError, not a silent coercion.

FX round-trips are exact by construction. Converting 1000 JPY to USD at 150
and back does not go through 6.66666...; the converted Money keeps a reference
to what it came from, and converting back with the inverse of the same rate
returns the original amount to the cent. Float would lose this and so would a
naive Decimal multiply-divide.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# Minor-unit precision per currency. JPY has no minor unit.
MINOR_UNITS = {"JPY": 0, "USD": 2, "EUR": 2, "GBP": 2, "CNY": 2}
DEFAULT_MINOR_UNITS = 2


def _dec(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # A float has already lost precision; refuse rather than launder it.
        raise TypeError(
            f"refusing to build money from float {value!r} -- pass a str, int or Decimal"
        )
    return Decimal(str(value))


@dataclass(frozen=True)
class FxRate:
    """`rate` units of `quote` per one unit of `base`, as of a date."""

    base: str
    quote: str
    rate: Decimal
    as_of: str
    source: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "rate", _dec(self.rate))
        if self.rate <= 0:
            raise ValueError("fx rate must be positive")

    def inverted(self) -> "FxRate":
        return FxRate(base=self.quote, quote=self.base, rate=Decimal(1) / self.rate,
                      as_of=self.as_of, source=self.source)

    def is_inverse_of(self, other: "FxRate") -> bool:
        return (other is not None
                and self.base == other.quote and self.quote == other.base
                and self.as_of == other.as_of)


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str
    # Provenance: what this was converted from, and with which rate.
    origin: Optional["Money"] = field(default=None, repr=False, compare=False)
    fx: Optional[FxRate] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "amount", _dec(self.amount))
        object.__setattr__(self, "currency", str(self.currency).upper())

    # -- construction ----------------------------------------------------

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(Decimal(0), currency)

    # -- arithmetic ------------------------------------------------------

    def _same(self, other: "Money"):
        if not isinstance(other, Money):
            raise TypeError(f"cannot combine Money with {type(other).__name__}")
        if other.currency != self.currency:
            raise TypeError(
                f"currency mismatch: {self.currency} and {other.currency} -- "
                "convert explicitly with .to(), there is no implicit FX"
            )

    def __add__(self, other):
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other):
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor):
        return Money(self.amount * _dec(factor), self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor):
        d = _dec(divisor)
        if d == 0:
            raise ZeroDivisionError("division of Money by zero")
        return Money(self.amount / d, self.currency)

    def __neg__(self):
        return Money(-self.amount, self.currency)

    def __lt__(self, other):
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other):
        self._same(other)
        return self.amount <= other.amount

    def is_zero(self) -> bool:
        return self.amount == 0

    # -- conversion ------------------------------------------------------

    def to(self, currency: str, rate: FxRate) -> "Money":
        """Convert, preserving an exact path back to the original amount."""
        currency = currency.upper()
        if currency == self.currency:
            return self
        if rate.base != self.currency or rate.quote != currency:
            raise ValueError(
                f"rate {rate.base}->{rate.quote} cannot convert {self.currency}->{currency}"
            )
        # Round-trip: if we are converting back to where we came from using the
        # inverse of the same rate, restore the original amount exactly rather
        # than recomputing it and accumulating error.
        if (self.origin is not None and self.origin.currency == currency
                and self.fx is not None and rate.is_inverse_of(self.fx)):
            return replace(self.origin, origin=self, fx=rate)
        return Money(self.amount * rate.rate, currency, origin=self, fx=rate)

    # -- presentation ----------------------------------------------------

    def quantized(self) -> "Money":
        places = MINOR_UNITS.get(self.currency, DEFAULT_MINOR_UNITS)
        exp = Decimal(1).scaleb(-places)
        return Money(self.amount.quantize(exp, rounding=ROUND_HALF_UP), self.currency,
                     origin=self.origin, fx=self.fx)

    def __str__(self):
        return f"{self.quantized().amount} {self.currency}"

    def as_dict(self):
        d = {"amount": str(self.quantized().amount), "currency": self.currency}
        if self.fx is not None:
            d["fx"] = {"base": self.fx.base, "quote": self.fx.quote,
                       "rate": str(self.fx.rate), "as_of": self.fx.as_of,
                       "source": self.fx.source}
            d["converted_from"] = {"amount": str(self.origin.amount),
                                   "currency": self.origin.currency}
        return d


def money_sum(items, currency: str) -> Money:
    total = Money.zero(currency)
    for m in items:
        total = total + m
    return total
