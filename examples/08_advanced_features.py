"""高级特性示例

演示多重绑定、Map 绑定、命名绑定、ProviderWrapper 懒注入和子容器。
"""

from __future__ import annotations

from typing import Annotated, Protocol, runtime_checkable

from autowire_di import Container, Named, ProviderWrapper, Scope


# ── 接口定义 ──────────────────────────────────────────────────────


@runtime_checkable
class EventHandler(Protocol):
    def handle(self, event: str) -> str: ...


@runtime_checkable
class CacheBackend(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


# ── 实现类 ────────────────────────────────────────────────────────


class LoggingHandler:
    def handle(self, event: str) -> str:
        return f"[LOG] {event}"


class MetricsHandler:
    def handle(self, event: str) -> str:
        return f"[METRIC] {event}"


class AlertHandler:
    def handle(self, event: str) -> str:
        return f"[ALERT] {event}"


class RedisCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def __repr__(self) -> str:
        return "RedisCache"


class MemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def __repr__(self) -> str:
        return "MemoryCache"


class DiskCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def __repr__(self) -> str:
        return "DiskCache"


class ExpensiveService:
    """模拟创建开销较大的服务。"""

    _counter = 0

    def __init__(self) -> None:
        ExpensiveService._counter += 1
        self.instance_id = ExpensiveService._counter
        print(f"    [ExpensiveService] Created instance #{self.instance_id}")

    def do_work(self) -> str:
        return f"work from #{self.instance_id}"


# ── 使用高级特性的服务 ────────────────────────────────────────────


class EventBus:
    """通过 list[EventHandler] 自动注入所有多重绑定。"""

    def __init__(self, handlers: list[EventHandler]) -> None:
        self.handlers = handlers

    def dispatch(self, event: str) -> list[str]:
        return [h.handle(event) for h in self.handlers]


class CacheManager:
    """通过 dict[str, CacheBackend] 自动注入所有 Map 绑定。"""

    def __init__(self, caches: dict[str, CacheBackend]) -> None:
        self.caches = caches

    def get_backend(self, name: str) -> CacheBackend:
        return self.caches[name]


class OrderService:
    """通过 Named 标记选择特定的缓存实现。"""

    def __init__(
        self,
        primary_cache: Annotated[CacheBackend, Named("primary")],
        fallback_cache: Annotated[CacheBackend, Named("fallback")],
    ) -> None:
        self.primary = primary_cache
        self.fallback = fallback_cache


class LazyConsumer:
    """通过 ProviderWrapper 延迟解析 ExpensiveService。"""

    def __init__(self, provider: ProviderWrapper[ExpensiveService]) -> None:
        self._provider = provider

    def use_service(self) -> str:
        svc = self._provider.get()
        return svc.do_work()


# ── 运行示例 ──────────────────────────────────────────────────────


def main() -> None:
    # ── 1. 多重绑定（Multi-binding） ──
    print("=== 多重绑定 ===")
    container = Container()
    container.register_multi(EventHandler, LoggingHandler)
    container.register_multi(EventHandler, MetricsHandler)
    container.register_multi(EventHandler, AlertHandler)

    handlers = container.resolve_multi(EventHandler)
    print(f"  Registered handlers: {len(handlers)}")

    bus = container.resolve(EventBus)
    results = bus.dispatch("user.created")
    for r in results:
        print(f"  {r}")

    # ── 2. Map 绑定 ──
    print("\n=== Map 绑定 ===")
    container.register_map(CacheBackend, "redis", RedisCache)
    container.register_map(CacheBackend, "memory", MemoryCache)
    container.register_map(CacheBackend, "disk", DiskCache)

    cache_map = container.resolve_map(CacheBackend)
    print(f"  Available backends: {list(cache_map.keys())}")

    manager = container.resolve(CacheManager)
    redis = manager.get_backend("redis")
    redis.set("key1", "value1")
    print(f"  Redis get('key1'): {redis.get('key1')}")

    # ── 3. 命名绑定 ──
    print("\n=== 命名绑定 ===")
    container.register(CacheBackend, RedisCache, name="primary")
    container.register(CacheBackend, MemoryCache, name="fallback")

    order_svc = container.resolve(OrderService)
    print(f"  Primary cache: {order_svc.primary}")
    print(f"  Fallback cache: {order_svc.fallback}")
    assert isinstance(order_svc.primary, RedisCache)
    assert isinstance(order_svc.fallback, MemoryCache)

    # ── 4. ProviderWrapper 懒注入 ──
    print("\n=== ProviderWrapper 懒注入 ===")
    container.register(ExpensiveService, scope=Scope.TRANSIENT)

    print("  Creating LazyConsumer (ExpensiveService NOT yet created):")
    consumer = container.resolve(LazyConsumer)
    print("  Calling use_service() — now it creates ExpensiveService:")
    result = consumer.use_service()
    print(f"  Result: {result}")
    print("  Calling again — creates another instance (TRANSIENT):")
    result2 = consumer.use_service()
    print(f"  Result: {result2}")

    # ── 5. 子容器 ──
    print("\n=== 子容器 ===")
    parent = Container()
    parent.register(CacheBackend, RedisCache)

    child = parent.create_child()
    child.override(CacheBackend, MemoryCache)

    parent_cache = parent.resolve(CacheBackend)
    child_cache = child.resolve(CacheBackend)
    print(f"  Parent: {parent_cache}")
    print(f"  Child:  {child_cache}")
    assert isinstance(parent_cache, RedisCache)
    assert isinstance(child_cache, MemoryCache)

    print("\n✓ 高级特性示例完成")


if __name__ == "__main__":
    main()
