"""Tests for Assisted Injection — partial injection with caller-provided params."""

from typing import Annotated, Protocol, runtime_checkable

import pytest

from autowire_di import Assisted, Container, Inject, Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@runtime_checkable
class IPaymentGateway(Protocol):
    def charge(self, amount: float) -> str: ...


class StripeGateway:
    def charge(self, amount: float) -> str:
        return f"stripe:{amount}"


class AuditLogger:
    def log(self, msg: str) -> None:
        pass


class Payment:
    def __init__(
        self,
        gateway: IPaymentGateway,
        amount: Annotated[float, Assisted()],
        currency: Annotated[str, Assisted()],
    ) -> None:
        self.gateway = gateway
        self.amount = amount
        self.currency = currency


class Order:
    def __init__(
        self,
        gateway: IPaymentGateway,
        logger: AuditLogger,
        item_name: Annotated[str, Assisted()],
        quantity: Annotated[int, Assisted()],
        discount: Annotated[float, Assisted()],
    ) -> None:
        self.gateway = gateway
        self.logger = logger
        self.item_name = item_name
        self.quantity = quantity
        self.discount = discount


class SimpleProduct:
    def __init__(
        self,
        name: Annotated[str, Assisted()],
        price: Annotated[float, Assisted()],
    ) -> None:
        self.name = name
        self.price = price


class ConfiguredPayment:
    def __init__(
        self,
        gateway: IPaymentGateway,
        fee_rate: Annotated[float, Inject(config="payment.fee_rate")],
        amount: Annotated[float, Assisted()],
    ) -> None:
        self.gateway = gateway
        self.fee_rate = fee_rate
        self.amount = amount


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAssistedInjectionBasic:
    def test_create_factory_basic(self) -> None:
        c = Container()
        c.register(IPaymentGateway, StripeGateway)

        make_payment = c.create_factory(Payment)
        payment = make_payment(amount=100.0, currency="USD")

        assert isinstance(payment, Payment)
        assert isinstance(payment.gateway, StripeGateway)
        assert payment.amount == 100.0
        assert payment.currency == "USD"

    def test_factory_name(self) -> None:
        c = Container()
        c.register(IPaymentGateway, StripeGateway)

        factory = c.create_factory(Payment)
        assert "Payment" in factory.__name__
        assert "Factory" in factory.__name__

    def test_factory_assisted_params_attribute(self) -> None:
        c = Container()
        c.register(IPaymentGateway, StripeGateway)

        factory = c.create_factory(Payment)
        assert "amount" in factory.__assisted_params__
        assert "currency" in factory.__assisted_params__


class TestAssistedMissingArgs:
    def test_missing_assisted_arg_raises(self) -> None:
        c = Container()
        c.register(IPaymentGateway, StripeGateway)

        make_payment = c.create_factory(Payment)
        with pytest.raises(TypeError, match="Missing assisted"):
            make_payment(amount=100.0)

    def test_missing_all_assisted_args_raises(self) -> None:
        c = Container()
        c.register(IPaymentGateway, StripeGateway)

        make_payment = c.create_factory(Payment)
        with pytest.raises(TypeError, match="Missing assisted"):
            make_payment()


class TestAssistedWithMultipleDeps:
    def test_multiple_injected_and_assisted(self) -> None:
        c = Container()
        c.register(IPaymentGateway, StripeGateway)
        c.register(AuditLogger)

        make_order = c.create_factory(Order)
        order = make_order(item_name="Widget", quantity=5, discount=0.1)

        assert isinstance(order, Order)
        assert isinstance(order.gateway, StripeGateway)
        assert isinstance(order.logger, AuditLogger)
        assert order.item_name == "Widget"
        assert order.quantity == 5
        assert order.discount == 0.1


class TestAssistedAllParams:
    def test_all_assisted_no_injection(self) -> None:
        c = Container()
        make_product = c.create_factory(SimpleProduct)
        product = make_product(name="Gadget", price=29.99)

        assert product.name == "Gadget"
        assert product.price == 29.99


class TestAssistedWithConfig:
    def test_assisted_with_config_injection(self) -> None:
        c = Container(config={"payment": {"fee_rate": 0.029}})
        c.register(IPaymentGateway, StripeGateway)

        make_payment = c.create_factory(ConfiguredPayment)
        payment = make_payment(amount=500.0)

        assert isinstance(payment.gateway, StripeGateway)
        assert payment.fee_rate == 0.029
        assert payment.amount == 500.0


class TestAssistedWithSingleton:
    def test_singleton_dep_shared_across_factory_calls(self) -> None:
        c = Container()
        c.register(IPaymentGateway, StripeGateway, scope=Scope.SINGLETON)

        make_payment = c.create_factory(Payment)
        p1 = make_payment(amount=100.0, currency="USD")
        p2 = make_payment(amount=200.0, currency="EUR")

        assert p1.gateway is p2.gateway
        assert p1.amount == 100.0
        assert p2.amount == 200.0
        assert p1.currency == "USD"
        assert p2.currency == "EUR"
