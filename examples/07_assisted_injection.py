"""Assisted 注入示例

演示 Assisted 标记和 create_factory：
- 部分参数由容器注入
- 部分参数由调用方在运行时提供
"""

from __future__ import annotations

from typing import Annotated, Protocol, runtime_checkable

from autowire_di import Assisted, Container, Scope


# ── 接口和实现 ────────────────────────────────────────────────────


@runtime_checkable
class PaymentGateway(Protocol):
    def charge(self, amount: float, currency: str) -> str: ...


@runtime_checkable
class Logger(Protocol):
    def log(self, message: str) -> None: ...


class StripeGateway:
    def charge(self, amount: float, currency: str) -> str:
        return f"stripe_txn_{amount:.0f}_{currency}"


class ConsoleLogger:
    def log(self, message: str) -> None:
        print(f"  [LOG] {message}")


# ── 使用 Assisted 标记的类 ────────────────────────────────────────


class Payment:
    """Payment 的构造参数中：
    - gateway 和 logger 由容器注入
    - amount 和 currency 由调用方提供
    """

    def __init__(
        self,
        gateway: PaymentGateway,
        logger: Logger,
        amount: Annotated[float, Assisted()],
        currency: Annotated[str, Assisted()],
    ) -> None:
        self.gateway = gateway
        self.logger = logger
        self.amount = amount
        self.currency = currency

    def execute(self) -> str:
        self.logger.log(f"Processing payment: {self.amount} {self.currency}")
        return self.gateway.charge(self.amount, self.currency)


class EmailNotification:
    """邮件通知：recipient 由调用方提供，logger 由容器注入。"""

    def __init__(
        self,
        logger: Logger,
        recipient: Annotated[str, Assisted()],
        subject: Annotated[str, Assisted()],
        body: Annotated[str, Assisted()],
    ) -> None:
        self.logger = logger
        self.recipient = recipient
        self.subject = subject
        self.body = body

    def send(self) -> str:
        self.logger.log(f"Sending email to {self.recipient}: {self.subject}")
        return f"sent to {self.recipient}"


# ── 运行示例 ──────────────────────────────────────────────────────


def main() -> None:
    container = Container()
    container.register(PaymentGateway, StripeGateway)
    container.register(Logger, ConsoleLogger, scope=Scope.SINGLETON)

    # ── 创建 Payment 工厂 ──
    print("=== Payment Factory ===")
    make_payment = container.create_factory(Payment)

    p1 = make_payment(amount=100.0, currency="USD")
    result1 = p1.execute()
    print(f"  Payment 1: {result1}")
    assert isinstance(p1.gateway, StripeGateway)

    p2 = make_payment(amount=50.0, currency="EUR")
    result2 = p2.execute()
    print(f"  Payment 2: {result2}")

    # gateway 和 logger 是容器注入的
    assert isinstance(p1.gateway, StripeGateway)
    assert isinstance(p1.logger, ConsoleLogger)
    # amount 和 currency 是调用方提供的
    assert p1.amount == 100.0
    assert p2.currency == "EUR"

    # ── 创建 EmailNotification 工厂 ──
    print("\n=== Email Factory ===")
    make_email = container.create_factory(EmailNotification)

    email = make_email(
        recipient="alice@example.com",
        subject="Order Confirmation",
        body="Your order has been placed.",
    )
    result = email.send()
    print(f"  Email: {result}")

    # ── 缺少 Assisted 参数会报错 ──
    print("\n=== Missing Assisted Args ===")
    try:
        make_payment(amount=100.0)  # 缺少 currency
    except TypeError as e:
        print(f"  Expected error: {e}")

    print("\n✓ Assisted 注入示例完成")


if __name__ == "__main__":
    main()
