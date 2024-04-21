from __future__ import annotations

from decimal import Decimal

import pytest

from corebank.domain.exceptions import (
    CurrencyMismatchError,
    InvalidAmountError,
    UnsupportedCurrencyError,
)
from corebank.domain.money import CURRENCIES, Money, minor_units, quantum, sum_money, to_decimal


class TestConstruction:
    def test_quantizes_to_minor_units(self) -> None:
        assert Money.of("10.1", "GBP").amount == Decimal("10.10")
        assert Money.of("10.1", "GBP").as_string() == "10.10"
        assert Money.of(100, "JPY").as_string() == "100"

    def test_currency_is_normalised(self) -> None:
        assert Money.of("1.00", " gbp ").currency == "GBP"

    @pytest.mark.parametrize("currency", sorted(CURRENCIES))
    def test_supported_currencies(self, currency: str) -> None:
        money = Money.of("1", currency)
        assert money.currency == currency
        assert minor_units(currency) == CURRENCIES[currency]
        assert quantum(currency) == Decimal(1).scaleb(-CURRENCIES[currency])

    @pytest.mark.parametrize("currency", ["XXX", "BTC", "", "GB", "GBPP"])
    def test_unsupported_currency(self, currency: str) -> None:
        with pytest.raises(UnsupportedCurrencyError) as exc:
            Money.of("1", currency)
        assert exc.value.code == "UNSUPPORTED_CURRENCY"

    def test_rejects_float(self) -> None:
        with pytest.raises(InvalidAmountError):
            Money(0.1, "GBP")  # type: ignore[arg-type]
        with pytest.raises(InvalidAmountError):
            to_decimal(0.1)  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        with pytest.raises(InvalidAmountError):
            to_decimal(True)  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "abc", "1,000", ""])
    def test_rejects_non_finite_or_junk(self, value: str) -> None:
        with pytest.raises(InvalidAmountError):
            Money.of(value, "GBP")

    def test_rejects_excess_precision_rather_than_rounding(self) -> None:
        with pytest.raises(InvalidAmountError) as exc:
            Money.of("10.001", "GBP")
        assert "precision" in exc.value.message
        with pytest.raises(InvalidAmountError):
            Money.of("100.5", "JPY")

    def test_rejects_magnitude_overflow(self) -> None:
        with pytest.raises(InvalidAmountError):
            Money.of("1000000000000000", "GBP")

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(InvalidAmountError):
            to_decimal(object())  # type: ignore[arg-type]

    def test_is_hashable_and_equal_by_value(self) -> None:
        assert Money.of("1.5", "GBP") == Money.of("1.50", "GBP")
        assert {Money.of("1.5", "GBP"), Money.of("1.50", "GBP")} == {Money.of("1.50", "GBP")}
        assert Money.of("1.50", "GBP") != Money.of("1.50", "USD")


class TestArithmetic:
    def test_add_sub_neg_abs(self) -> None:
        a = Money.of("10.00", "GBP")
        b = Money.of("0.10", "GBP")
        assert (a + b).as_string() == "10.10"
        assert (b - a).as_string() == "-9.90"
        assert (-a).as_string() == "-10.00"
        assert abs(b - a) == Money.of("9.90", "GBP")

    def test_no_binary_float_drift(self) -> None:
        total = Money.zero("GBP")
        for _ in range(10):
            total = total + Money.of("0.10", "GBP")
        assert total == Money.of("1.00", "GBP")

    def test_currency_mismatch(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            Money.of("1", "GBP") + Money.of("1", "USD")
        with pytest.raises(CurrencyMismatchError):
            _ = Money.of("1", "GBP") < Money.of("1", "USD")

    def test_type_error_for_non_money(self) -> None:
        with pytest.raises(TypeError):
            Money.of("1", "GBP") + 1  # type: ignore[operator]

    def test_comparisons_and_predicates(self) -> None:
        one = Money.of("1", "GBP")
        two = Money.of("2", "GBP")
        assert one < two and one <= two and two > one and two >= one
        assert one.is_positive and not one.is_negative and not one.is_zero
        assert (one - one).is_zero
        assert (one - two).is_negative

    def test_sum_money(self) -> None:
        assert sum_money([], "GBP") == Money.zero("GBP")
        items = [Money.of("1.10", "GBP"), Money.of("2.20", "GBP")]
        assert sum_money(items, "GBP") == Money.of("3.30", "GBP")

    def test_str(self) -> None:
        assert str(Money.of("1.5", "GBP")) == "1.50 GBP"
