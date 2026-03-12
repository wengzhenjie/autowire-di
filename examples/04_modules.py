"""模块系统示例

演示 Module 和 PrivateModule 的用法：
- Module：将相关绑定组织为可复用的模块
- PrivateModule：封装内部实现，仅暴露公开接口
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from autowire_di import (
    Container,
    Module,
    PrivateModule,
    Scope,
)


# ── 接口定义 ──────────────────────────────────────────────────────


@runtime_checkable
class Logger(Protocol):
    def log(self, message: str) -> None: ...


@runtime_checkable
class UserRepository(Protocol):
    def find(self, user_id: int) -> dict: ...


@runtime_checkable
class PaymentGateway(Protocol):
    def charge(self, amount: float) -> str: ...


# ── 实现类 ────────────────────────────────────────────────────────


class ConsoleLogger:
    def log(self, message: str) -> None:
        print(f"  [LOG] {message}")


class InMemoryUserRepository:
    def __init__(self, logger: Logger) -> None:
        self.logger = logger

    def find(self, user_id: int) -> dict:
        self.logger.log(f"Finding user {user_id}")
        return {"id": user_id, "name": f"User-{user_id}"}


class StripeGateway:
    def __init__(self, logger: Logger) -> None:
        self.logger = logger

    def charge(self, amount: float) -> str:
        self.logger.log(f"Charging ${amount:.2f} via Stripe")
        return f"txn_{amount:.0f}"


class InternalValidator:
    """内部实现细节，不应对外暴露。"""

    def validate(self, amount: float) -> bool:
        return amount > 0


class PaymentService:
    """支付服务，依赖网关和内部验证器。"""

    def __init__(
        self,
        gateway: PaymentGateway,
        validator: InternalValidator,
        logger: Logger,
    ) -> None:
        self.gateway = gateway
        self.validator = validator
        self.logger = logger

    def process(self, amount: float) -> str:
        if not self.validator.validate(amount):
            raise ValueError("Invalid amount")
        self.logger.log(f"Processing payment of ${amount:.2f}")
        return self.gateway.charge(amount)


# ── Module：公开模块 ──────────────────────────────────────────────


class InfraModule(Module):
    """基础设施模块：日志和用户仓库。"""

    def configure(self, container: Container) -> None:
        container.register(Logger, ConsoleLogger, scope=Scope.SINGLETON)
        container.register(UserRepository, InMemoryUserRepository)


# ── PrivateModule：私有模块 ───────────────────────────────────────


class PaymentModule(PrivateModule):
    """支付模块：内部实现对外不可见，仅暴露 PaymentService。"""

    def configure(self, container: Container) -> None:
        container.register(StripeGateway)
        container.register(PaymentGateway, StripeGateway)
        container.register(InternalValidator)
        container.register(PaymentService)
        self.expose(PaymentService)


# ── 运行示例 ──────────────────────────────────────────────────────


def main() -> None:
    container = Container()

    # 安装模块
    container.install(InfraModule())
    container.install(PaymentModule())

    # 公开模块的绑定可以正常解析
    print("=== 公开模块 ===")
    repo = container.resolve(UserRepository)
    user = repo.find(42)
    print(f"  Found: {user}")

    # 私有模块暴露的接口可以解析
    print("\n=== 私有模块（暴露的接口） ===")
    payment = container.resolve(PaymentService)
    txn = payment.process(99.99)
    print(f"  Transaction: {txn}")

    # 私有模块的内部实现不可见
    print("\n=== 私有模块（内部实现） ===")
    try:
        container.resolve(StripeGateway)
        print("  StripeGateway: auto-wired (concrete class, no private deps)")
    except ResolutionError as e:
        print(f"  StripeGateway: {e}")
    print("  Note: concrete classes can still be auto-wired,")
    print("  but abstract interfaces registered only in the private module are hidden.")

    print("\n✓ 模块系统示例完成")


if __name__ == "__main__":
    main()
