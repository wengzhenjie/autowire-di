"""AOP 方法拦截示例

演示如何使用 bind_interceptor 声明式地添加横切关注点：
- 日志拦截器
- 计时拦截器
- Matcher 组合
- 方法级别标记
"""

from __future__ import annotations

import time
from typing import Any

from autowire_di import (
    Container,
    MethodInterceptor,
    MethodInvocation,
    annotated_with,
    any_class,
    any_method,
    aop_mark,
    name_matches,
)


# ── AOP 标记 ──────────────────────────────────────────────────────


class Logged:
    """标记需要日志记录的类。"""


class Timed:
    """标记需要计时的类。"""


# ── 拦截器实现 ────────────────────────────────────────────────────


class LogInterceptor(MethodInterceptor):
    """记录方法调用的入参和返回值。"""

    def invoke(self, invocation: MethodInvocation) -> Any:
        name = invocation.method.__name__
        args_str = ", ".join(repr(a) for a in invocation.args)
        if invocation.kwargs:
            kwargs_str = ", ".join(f"{k}={v!r}" for k, v in invocation.kwargs.items())
            args_str = f"{args_str}, {kwargs_str}" if args_str else kwargs_str
        print(f"  → {name}({args_str})")
        result = invocation.proceed()
        print(f"  ← {name} = {result!r}")
        return result


class TimingInterceptor(MethodInterceptor):
    """测量方法执行时间。"""

    def invoke(self, invocation: MethodInvocation) -> Any:
        name = invocation.method.__name__
        start = time.perf_counter()
        result = invocation.proceed()
        elapsed = (time.perf_counter() - start) * 1000
        print(f"  ⏱ {name} took {elapsed:.2f}ms")
        return result


# ── 业务类 ────────────────────────────────────────────────────────


@aop_mark(Logged, Timed)
class OrderService:
    def place_order(self, item: str, quantity: int = 1) -> str:
        time.sleep(0.01)
        return f"Order: {quantity}x {item}"

    def cancel_order(self, order_id: str) -> str:
        return f"Cancelled: {order_id}"

    def _internal_method(self) -> str:
        return "internal"


@aop_mark(Logged)
class UserService:
    def get_user(self, user_id: int) -> dict:
        return {"id": user_id, "name": f"User-{user_id}"}

    def list_users(self) -> list[str]:
        return ["Alice", "Bob", "Charlie"]


# ── 运行示例 ──────────────────────────────────────────────────────


def main() -> None:
    container = Container()

    # 注册服务（拦截器只对通过绑定解析的实例生效）
    container.register(OrderService)
    container.register(UserService)

    # 为 @Logged 标记的类绑定日志拦截器
    container.bind_interceptor(
        class_matcher=annotated_with(Logged),
        method_matcher=any_method(),
        interceptor=LogInterceptor(),
    )

    # 为 @Timed 标记的类绑定计时拦截器（仅匹配 place_* 方法）
    container.bind_interceptor(
        class_matcher=annotated_with(Timed),
        method_matcher=name_matches("place_*"),
        interceptor=TimingInterceptor(),
    )

    # ── 测试 OrderService（同时有 Logged + Timed） ──
    print("=== OrderService.place_order ===")
    order_svc = container.resolve(OrderService)
    result = order_svc.place_order("Python Book", quantity=2)
    print(f"  Result: {result}")

    print("\n=== OrderService.cancel_order ===")
    result = order_svc.cancel_order("ORD-001")
    print(f"  Result: {result}")

    # ── 测试 UserService（仅 Logged） ──
    print("\n=== UserService.get_user ===")
    user_svc = container.resolve(UserService)
    user = user_svc.get_user(42)
    print(f"  Result: {user}")

    # ── Matcher 组合示例 ──
    print("\n=== Matcher 组合 ===")
    container2 = Container()
    container2.register(UserService)

    # 仅拦截 @Logged 类中名称以 get_ 或 list_ 开头的方法
    combined_matcher = name_matches("get_*") | name_matches("list_*")
    container2.bind_interceptor(
        class_matcher=annotated_with(Logged),
        method_matcher=combined_matcher,
        interceptor=LogInterceptor(),
    )

    user_svc2 = container2.resolve(UserService)
    print("  get_user (matched):")
    user_svc2.get_user(1)
    print("  list_users (matched):")
    user_svc2.list_users()

    # ── 取反 Matcher ──
    print("\n=== 取反 Matcher（排除 cancel_*） ===")
    container3 = Container()
    container3.register(OrderService)
    container3.bind_interceptor(
        class_matcher=any_class(),
        method_matcher=~name_matches("cancel_*"),
        interceptor=LogInterceptor(),
    )

    order_svc3 = container3.resolve(OrderService)
    print("  place_order (intercepted):")
    order_svc3.place_order("Book")
    print("  cancel_order (NOT intercepted):")
    order_svc3.cancel_order("ORD-002")

    print("\n✓ AOP 方法拦截示例完成")


if __name__ == "__main__":
    main()
