"""Tests for Assisted injection and create_factory."""

from __future__ import annotations

from typing import Annotated, Protocol, runtime_checkable

import pytest

from autowire_di import Assisted, Container, Inject, Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@runtime_checkable
class PaymentGateway(Protocol):
    def charge(self, amount: float) -> str: ...


class StripeGateway:
    def charge(self, amount: float) -> str:
        return f"stripe:{amount}"


class Payment:
    def __init__(
        self,
        gateway: PaymentGateway,
        amount: Annotated[float, Assisted()],
        currency: Annotated[str, Assisted()],
    ) -> None:
        self.gateway = gateway
        self.amount = amount
        self.currency = currency


class OrderWithConfig:
    def __init__(
        self,
        gateway: PaymentGateway,
        region: Annotated[str, Inject(config="order.region")],
        amount: Annotated[float, Assisted()],
    ) -> None:
        self.gateway = gateway
        self.region = region
        self.amount = amount


class NoAssistedParams:
    def __init__(self, gateway: PaymentGateway) -> None:
        self.gateway = gateway


# ---------------------------------------------------------------------------
# Basic create_factory
# ---------------------------------------------------------------------------


class TestCreateFactory:
    def test_basic_factory(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway)

        make_payment = c.create_factory(Payment)
        p = make_payment(amount=99.99, currency="USD")

        assert isinstance(p, Payment)
        assert isinstance(p.gateway, StripeGateway)
        assert p.amount == 99.99
        assert p.currency == "USD"

    def test_factory_missing_assisted_raises(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway)

        make_payment = c.create_factory(Payment)
        with pytest.raises(TypeError, match="Missing assisted argument"):
            make_payment(amount=10.0)

    def test_factory_with_extra_kwargs_ok(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway)

        make_payment = c.create_factory(Payment)
        p = make_payment(amount=1.0, currency="EUR")
        assert p.currency == "EUR"

    def test_factory_name_and_qualname(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway)

        factory = c.create_factory(Payment)
        assert factory.__name__ == "PaymentFactory"
        assert "PaymentFactory" in factory.__qualname__

    def test_factory_assisted_params_attribute(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway)

        factory = c.create_factory(Payment)
        assert set(factory.__assisted_params__) == {"amount", "currency"}

    def test_no_assisted_params_factory(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway)

        factory = c.create_factory(NoAssistedParams)
        obj = factory()
        assert isinstance(obj.gateway, StripeGateway)


# ---------------------------------------------------------------------------
# Assisted + Config injection
# ---------------------------------------------------------------------------


class TestAssistedWithConfig:
    def test_factory_with_config_injection(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway)
        c.set_config({"order": {"region": "US"}})

        factory = c.create_factory(OrderWithConfig)
        order = factory(amount=50.0)

        assert order.region == "US"
        assert order.amount == 50.0
        assert isinstance(order.gateway, StripeGateway)


# ---------------------------------------------------------------------------
# Assisted with scoped container
# ---------------------------------------------------------------------------


class TestAssistedInScope:
    def test_factory_in_scope(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway, scope=Scope.SCOPED)

        with c.new_scope() as scope:
            factory = scope.create_factory(Payment)
            p = factory(amount=10.0, currency="JPY")
            assert isinstance(p.gateway, StripeGateway)
            assert p.currency == "JPY"


# ---------------------------------------------------------------------------
# Assisted params skipped during normal resolve
# ---------------------------------------------------------------------------


class TestAssistedSkippedInResolve:
    def test_resolve_callable_args_skips_assisted(self) -> None:
        c = Container()
        c.register(PaymentGateway, StripeGateway)

        kwargs = c.resolve_callable_args(
            Payment.__init__,
            config=None,
        )
        assert "gateway" in kwargs
        assert "amount" not in kwargs
        assert "currency" not in kwargs
