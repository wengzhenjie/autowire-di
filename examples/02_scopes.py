"""三种作用域示例

演示 Transient / Singleton / Scoped 三种生命周期的行为差异。
"""

from __future__ import annotations

import threading

from autowire_di import Container, Scope


# ── 服务类 ────────────────────────────────────────────────────────

_counter = 0
_lock = threading.Lock()


def _next_id() -> int:
    global _counter
    with _lock:
        _counter += 1
        return _counter


class TransientService:
    """每次解析都创建新实例。"""

    def __init__(self) -> None:
        self.instance_id = _next_id()

    def __repr__(self) -> str:
        return f"TransientService(#{self.instance_id})"


class SingletonService:
    """全局唯一实例，线程安全。"""

    def __init__(self) -> None:
        self.instance_id = _next_id()

    def __repr__(self) -> str:
        return f"SingletonService(#{self.instance_id})"


class ScopedService:
    """同一作用域内共享，不同作用域间隔离。"""

    def __init__(self) -> None:
        self.instance_id = _next_id()

    def __repr__(self) -> str:
        return f"ScopedService(#{self.instance_id})"


# ── 运行示例 ──────────────────────────────────────────────────────


def main() -> None:
    container = Container()

    container.register(TransientService, scope=Scope.TRANSIENT)
    container.register(SingletonService, scope=Scope.SINGLETON)
    container.register(ScopedService, scope=Scope.SCOPED)

    # ── Transient：每次都是新实例 ──
    print("=== Transient ===")
    t1 = container.resolve(TransientService)
    t2 = container.resolve(TransientService)
    print(f"  {t1}")
    print(f"  {t2}")
    assert t1 is not t2
    print(f"  t1 is t2? {t1 is t2}")

    # ── Singleton：始终同一实例 ──
    print("\n=== Singleton ===")
    s1 = container.resolve(SingletonService)
    s2 = container.resolve(SingletonService)
    print(f"  {s1}")
    print(f"  {s2}")
    assert s1 is s2
    print(f"  s1 is s2? {s1 is s2}")

    # ── Scoped：同一作用域内共享，跨作用域隔离 ──
    print("\n=== Scoped ===")
    with container.new_scope() as scope_a:
        a1 = scope_a.resolve(ScopedService)
        a2 = scope_a.resolve(ScopedService)
        print(f"  Scope A: {a1}")
        print(f"  Scope A: {a2}")
        assert a1 is a2
        print(f"  a1 is a2? {a1 is a2}")

    with container.new_scope() as scope_b:
        b1 = scope_b.resolve(ScopedService)
        print(f"  Scope B: {b1}")
        assert b1 is not a1
        print(f"  b1 is a1? {b1 is a1}")

    # ── Singleton 在子作用域中也是同一实例 ──
    print("\n=== Singleton in scopes ===")
    with container.new_scope() as scope_c:
        s3 = scope_c.resolve(SingletonService)
        print(f"  Root singleton: {s1}")
        print(f"  Scoped resolve: {s3}")
        assert s1 is s3
        print(f"  Same instance? {s1 is s3}")

    print("\n✓ 三种作用域示例完成")


if __name__ == "__main__":
    main()
