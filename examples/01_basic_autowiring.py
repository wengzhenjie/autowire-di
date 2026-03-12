"""基本自动装配示例

演示 autowire-di 的核心能力：通过 __init__ 类型注解自动构建依赖图。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from autowire_di import Container


# ── 定义接口（Protocol） ──────────────────────────────────────────


@runtime_checkable
class UserRepository(Protocol):
    def find_by_id(self, user_id: int) -> dict: ...
    def save(self, user: dict) -> None: ...


@runtime_checkable
class NotificationService(Protocol):
    def send(self, user_id: int, message: str) -> None: ...


# ── 实现类 ────────────────────────────────────────────────────────


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._store: dict[int, dict] = {
            1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
            2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
        }

    def find_by_id(self, user_id: int) -> dict:
        user = self._store.get(user_id)
        if user is None:
            raise KeyError(f"User {user_id} not found")
        return user

    def save(self, user: dict) -> None:
        self._store[user["id"]] = user


class ConsoleNotificationService:
    def send(self, user_id: int, message: str) -> None:
        print(f"  [Notification] → User {user_id}: {message}")


# ── 业务服务（依赖通过类型注解声明） ──────────────────────────────


class UserService:
    """UserService 依赖 UserRepository 和 NotificationService。
    容器会自动检查 __init__ 的类型注解并注入对应实现。"""

    def __init__(
        self,
        repo: UserRepository,
        notifier: NotificationService,
    ) -> None:
        self.repo = repo
        self.notifier = notifier

    def get_user(self, user_id: int) -> dict:
        return self.repo.find_by_id(user_id)

    def update_email(self, user_id: int, new_email: str) -> None:
        user = self.repo.find_by_id(user_id)
        user["email"] = new_email
        self.repo.save(user)
        self.notifier.send(user_id, f"Email updated to {new_email}")


# ── 运行示例 ──────────────────────────────────────────────────────


def main() -> None:
    container = Container()

    # 注册接口 → 实现的映射
    container.register(UserRepository, InMemoryUserRepository)
    container.register(NotificationService, ConsoleNotificationService)

    # UserService 未注册，但容器能通过类型注解自动构造它
    service = container.resolve(UserService)

    # 验证自动装配结果
    assert isinstance(service.repo, InMemoryUserRepository)
    assert isinstance(service.notifier, ConsoleNotificationService)

    # 使用服务
    user = service.get_user(1)
    print(f"User: {user}")

    service.update_email(1, "alice-new@example.com")
    updated = service.get_user(1)
    print(f"Updated: {updated}")

    # 具体类也可以直接解析（无需注册）
    repo = container.resolve(InMemoryUserRepository)
    assert isinstance(repo, InMemoryUserRepository)
    print(f"\nDirect resolve of concrete class: {type(repo).__name__}")

    print("\n✓ 基本自动装配示例完成")


if __name__ == "__main__":
    main()
