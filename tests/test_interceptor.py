"""Tests for AOP method interception."""

from __future__ import annotations

from typing import Any

from autowire_di import (
    Container,
    MethodInterceptor,
    MethodInvocation,
    Scope,
    annotated_with,
    any_class,
    any_method,
    aop_mark,
    name_matches,
    subclass_of,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class Transactional:
    pass


class Logged:
    pass


class LogInterceptor(MethodInterceptor):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, invocation: MethodInvocation) -> Any:
        self.calls.append(invocation.method.__name__)
        return invocation.proceed()


class UpperCaseInterceptor(MethodInterceptor):
    """Transforms string return values to uppercase."""

    def invoke(self, invocation: MethodInvocation) -> Any:
        result = invocation.proceed()
        if isinstance(result, str):
            return result.upper()
        return result


class TimesTwo(MethodInterceptor):
    def invoke(self, invocation: MethodInvocation) -> Any:
        return invocation.proceed() * 2


@aop_mark(Transactional)
class OrderService:
    def place_order(self, item: str) -> str:
        return f"ordered:{item}"

    def cancel_order(self, order_id: int) -> str:
        return f"cancelled:{order_id}"

    def _private_method(self) -> str:
        return "private"


class PaymentService:
    @aop_mark(Logged)
    def charge(self, amount: float) -> str:
        return f"charged:{amount}"

    def refund(self, amount: float) -> str:
        return f"refunded:{amount}"


class SimpleService:
    def greet(self, name: str) -> str:
        return f"hello {name}"


class SlotsService:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value

    def compute(self) -> int:
        return self.value * 10


class FrozenDataService:
    __slots__ = ("_x", "_y")

    def __init__(self, x: int, y: int) -> None:
        object.__setattr__(self, "_x", x)
        object.__setattr__(self, "_y", y)

    def sum(self) -> int:
        return self._x + self._y


# ---------------------------------------------------------------------------
# Basic interception
# ---------------------------------------------------------------------------


class TestBasicInterception:
    def test_intercept_all_methods_of_annotated_class(self) -> None:
        log = LogInterceptor()
        c = Container()
        c.register(OrderService)
        c.bind_interceptor(annotated_with(Transactional), any_method(), log)

        svc = c.resolve(OrderService)
        result = svc.place_order("book")

        assert result == "ordered:book"
        assert "place_order" in log.calls

    def test_interceptor_can_modify_return_value(self) -> None:
        c = Container()
        c.register(OrderService)
        c.bind_interceptor(annotated_with(Transactional), any_method(), UpperCaseInterceptor())

        svc = c.resolve(OrderService)
        assert svc.place_order("book") == "ORDERED:BOOK"

    def test_private_methods_not_intercepted(self) -> None:
        log = LogInterceptor()
        c = Container()
        c.register(OrderService)
        c.bind_interceptor(annotated_with(Transactional), any_method(), log)

        svc = c.resolve(OrderService)
        assert svc._private_method() == "private"
        assert "_private_method" not in log.calls

    def test_no_interception_when_class_doesnt_match(self) -> None:
        log = LogInterceptor()
        c = Container()
        c.register(SimpleService)
        c.bind_interceptor(annotated_with(Transactional), any_method(), log)

        svc = c.resolve(SimpleService)
        assert svc.greet("world") == "hello world"
        assert log.calls == []

    def test_no_interceptors_returns_original_instance(self) -> None:
        c = Container()
        c.register(SimpleService)
        svc = c.resolve(SimpleService)
        assert type(svc).__name__ == "SimpleService"


# ---------------------------------------------------------------------------
# Dynamic subclass proxy (works with __slots__)
# ---------------------------------------------------------------------------


class TestProxyWithSlots:
    def test_slots_class_intercepted(self) -> None:
        c = Container()
        c.register(SlotsService, factory=lambda: SlotsService(5))
        c.bind_interceptor(any_class(), any_method(), TimesTwo())

        svc = c.resolve(SlotsService)
        assert svc.compute() == 100  # 5*10=50, *2=100
        assert svc.value == 5

    def test_frozen_like_slots_class(self) -> None:
        c = Container()
        c.register(FrozenDataService, factory=lambda: FrozenDataService(3, 7))
        c.bind_interceptor(any_class(), any_method(), TimesTwo())

        svc = c.resolve(FrozenDataService)
        assert svc.sum() == 20  # (3+7)=10, *2=20

    def test_proxy_is_subclass(self) -> None:
        c = Container()
        c.register(OrderService)
        c.bind_interceptor(annotated_with(Transactional), any_method(), LogInterceptor())

        svc = c.resolve(OrderService)
        assert isinstance(svc, OrderService)
        assert hasattr(type(svc), "__intercepted__")


# ---------------------------------------------------------------------------
# Matchers
# ---------------------------------------------------------------------------


class TestMatchers:
    def test_subclass_of_matcher(self) -> None:
        class Base:
            pass

        @aop_mark(Transactional)
        class Child(Base):
            def work(self) -> str:
                return "child"

        log = LogInterceptor()
        c = Container()
        c.register(Child)
        c.bind_interceptor(subclass_of(Base), any_method(), log)

        svc = c.resolve(Child)
        svc.work()
        assert "work" in log.calls

    def test_name_matches_method_matcher(self) -> None:
        log = LogInterceptor()
        c = Container()
        c.register(OrderService)
        c.bind_interceptor(
            annotated_with(Transactional),
            name_matches("place_*"),
            log,
        )

        svc = c.resolve(OrderService)
        svc.place_order("x")
        svc.cancel_order(1)
        assert log.calls == ["place_order"]

    def test_and_matcher(self) -> None:
        m = annotated_with(Transactional) & subclass_of(object)
        assert m.matches(OrderService) is True

    def test_or_matcher(self) -> None:
        m = annotated_with(Transactional) | annotated_with(Logged)
        assert m.matches(OrderService) is True

    def test_not_matcher(self) -> None:
        m = ~annotated_with(Transactional)
        assert m.matches(OrderService) is False
        assert m.matches(SimpleService) is True


# ---------------------------------------------------------------------------
# Interceptor chain (multiple interceptors)
# ---------------------------------------------------------------------------


class TestInterceptorChain:
    def test_multiple_interceptors_applied_in_order(self) -> None:
        c = Container()
        c.register(OrderService)
        c.bind_interceptor(annotated_with(Transactional), any_method(), UpperCaseInterceptor())
        c.bind_interceptor(annotated_with(Transactional), any_method(), TimesTwo())

        svc = c.resolve(OrderService)
        result = svc.place_order("x")
        assert result == "ORDERED:XORDERED:X"


# ---------------------------------------------------------------------------
# Scoped interception
# ---------------------------------------------------------------------------


class TestScopedInterception:
    def test_interceptor_applies_in_scope(self) -> None:
        log = LogInterceptor()
        c = Container()
        c.register(OrderService, scope=Scope.SCOPED)
        c.bind_interceptor(annotated_with(Transactional), any_method(), log)

        with c.new_scope() as scope:
            svc = scope.resolve(OrderService)
            svc.place_order("y")
            assert "place_order" in log.calls

    def test_singleton_intercepted_once(self) -> None:
        log = LogInterceptor()
        c = Container()
        c.register(OrderService, scope=Scope.SINGLETON)
        c.bind_interceptor(annotated_with(Transactional), any_method(), log)

        svc1 = c.resolve(OrderService)
        svc2 = c.resolve(OrderService)
        assert svc1 is svc2
        svc1.place_order("a")
        assert len(log.calls) == 1


# ---------------------------------------------------------------------------
# Child container inherits interceptors
# ---------------------------------------------------------------------------


class TestChildContainerInterceptors:
    def test_child_inherits_parent_interceptors(self) -> None:
        log = LogInterceptor()
        parent = Container()
        parent.bind_interceptor(annotated_with(Transactional), any_method(), log)

        child = parent.create_child()
        child.register(OrderService)

        svc = child.resolve(OrderService)
        svc.place_order("z")
        assert "place_order" in log.calls


# ---------------------------------------------------------------------------
# Recipe serialization of interceptors
# ---------------------------------------------------------------------------


class TestInterceptorRecipe:
    def test_bind_interceptor_survives_recipe_rebuild(self) -> None:
        log = LogInterceptor()
        c = Container()
        c.register(OrderService)
        c.bind_interceptor(annotated_with(Transactional), any_method(), log)

        recipe = c.recipe
        rebuilt = recipe.build()

        svc = rebuilt.resolve(OrderService)
        svc.place_order("recipe")
        assert isinstance(svc, OrderService)

    def test_recipe_roundtrip_with_cloudpickle(self) -> None:
        import cloudpickle

        log = LogInterceptor()
        c = Container()
        c.register(OrderService)
        c.bind_interceptor(annotated_with(Transactional), any_method(), log)

        data = cloudpickle.dumps(c.recipe)
        recipe = cloudpickle.loads(data)
        rebuilt = recipe.build()

        svc = rebuilt.resolve(OrderService)
        svc.place_order("pickle")
        assert isinstance(svc, OrderService)


# ---------------------------------------------------------------------------
# aop_mark on methods
# ---------------------------------------------------------------------------


class TestMethodLevelMarkers:
    def test_aop_mark_on_class(self) -> None:
        assert Transactional in getattr(OrderService, "__aop_markers__", set())

    def test_aop_mark_on_method(self) -> None:
        assert Logged in getattr(PaymentService.charge, "__aop_markers__", set())
