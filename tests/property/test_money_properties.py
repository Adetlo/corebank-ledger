"""Property-based tests for the Money value object (pure domain, no database)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from corebank.domain.money import CURRENCIES, Money, quantum

currencies = st.sampled_from(sorted(CURRENCIES))


@st.composite
def money(draw, currency: str | None = None) -> Money:  # type: ignore[no-untyped-def]
    code = currency or draw(currencies)
    units = draw(st.integers(min_value=-(10**12), max_value=10**12))
    return Money(Decimal(units) * quantum(code), code)


@given(currencies, st.data())
@settings(max_examples=200)
def test_addition_is_commutative_and_associative(currency: str, data: st.DataObject) -> None:
    a, b, c = (data.draw(money(currency)) for _ in range(3))
    assert a + b == b + a
    assert (a + b) + c == a + (b + c)


@given(currencies, st.data())
def test_subtraction_inverts_addition(currency: str, data: st.DataObject) -> None:
    a, b = data.draw(money(currency)), data.draw(money(currency))
    assert (a + b) - b == a
    assert a - a == Money.zero(currency)


@given(st.data())
def test_amounts_are_always_quantized(data: st.DataObject) -> None:
    m = data.draw(money())
    assert m.amount == m.amount.quantize(quantum(m.currency))
    assert Money.of(m.as_string(), m.currency) == m  # round-trips through its string form
