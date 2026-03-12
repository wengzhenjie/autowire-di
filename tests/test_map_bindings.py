"""Tests for map-bindings: register_map / resolve_map / dict[str, T] auto-wiring."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pytest

from autowire_di import Container, ResolutionError, Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@runtime_checkable
class IStrategy(Protocol):
    def execute(self) -> str: ...


class StrategyA:
    def execute(self) -> str:
        return "A"


class StrategyB:
    def execute(self) -> str:
        return "B"


class StrategyC:
    def execute(self) -> str:
        return "C"


class StrategyConsumer:
    def __init__(self, strategies: dict[str, IStrategy]) -> None:
        self.strategies = strategies


# ---------------------------------------------------------------------------
# Basic map-binding
# ---------------------------------------------------------------------------


class TestMapBindingBasic:
    def test_register_and_resolve_map(self) -> None:
        c = Container()
        c.register_map(IStrategy, "a", StrategyA)
        c.register_map(IStrategy, "b", StrategyB)

        result = c.resolve_map(IStrategy)
        assert set(result.keys()) == {"a", "b"}
        assert result["a"].execute() == "A"
        assert result["b"].execute() == "B"

    def test_resolve_map_empty_raises(self) -> None:
        c = Container()
        with pytest.raises(ResolutionError, match="No map-bindings"):
            c.resolve_map(IStrategy)

    def test_map_binding_overwrites_same_key(self) -> None:
        c = Container()
        c.register_map(IStrategy, "x", StrategyA)
        c.register_map(IStrategy, "x", StrategyB)

        result = c.resolve_map(IStrategy)
        assert result["x"].execute() == "B"

    def test_map_with_instance(self) -> None:
        c = Container()
        inst = StrategyA()
        c.register_map(IStrategy, "fixed", instance=inst)

        result = c.resolve_map(IStrategy)
        assert result["fixed"] is inst

    def test_map_with_factory(self) -> None:
        c = Container()
        c.register_map(IStrategy, "factory", factory=lambda: StrategyC())

        result = c.resolve_map(IStrategy)
        assert result["factory"].execute() == "C"


# ---------------------------------------------------------------------------
# dict[str, T] auto-wiring
# ---------------------------------------------------------------------------


class TestMapAutoWiring:
    def test_dict_type_hint_auto_injects_map(self) -> None:
        c = Container()
        c.register_map(IStrategy, "a", StrategyA)
        c.register_map(IStrategy, "b", StrategyB)

        consumer = c.resolve(StrategyConsumer)
        assert set(consumer.strategies.keys()) == {"a", "b"}
        assert consumer.strategies["a"].execute() == "A"


# ---------------------------------------------------------------------------
# Map-bindings with scopes
# ---------------------------------------------------------------------------


class TestMapBindingScopes:
    def test_map_singleton_returns_same_instance(self) -> None:
        c = Container()
        c.register_map(IStrategy, "s", StrategyA, scope=Scope.SINGLETON)

        r1 = c.resolve_map(IStrategy)
        r2 = c.resolve_map(IStrategy)
        assert r1["s"] is r2["s"]

    def test_map_transient_returns_new_instance(self) -> None:
        c = Container()
        c.register_map(IStrategy, "t", StrategyA, scope=Scope.TRANSIENT)

        r1 = c.resolve_map(IStrategy)
        r2 = c.resolve_map(IStrategy)
        assert r1["t"] is not r2["t"]

    def test_map_scoped_in_scope(self) -> None:
        c = Container()
        c.register_map(IStrategy, "sc", StrategyA, scope=Scope.SCOPED)

        with c.new_scope() as scope:
            r1 = scope.resolve_map(IStrategy)
            r2 = scope.resolve_map(IStrategy)
            assert r1["sc"] is r2["sc"]


# ---------------------------------------------------------------------------
# Child container inherits map-bindings
# ---------------------------------------------------------------------------


class TestMapBindingInheritance:
    def test_child_inherits_parent_map(self) -> None:
        parent = Container()
        parent.register_map(IStrategy, "parent_a", StrategyA)

        child = parent.create_child()
        child.register_map(IStrategy, "child_b", StrategyB)

        result = child.resolve_map(IStrategy)
        assert set(result.keys()) == {"parent_a", "child_b"}

    def test_child_overrides_parent_key(self) -> None:
        parent = Container()
        parent.register_map(IStrategy, "x", StrategyA)

        child = parent.create_child()
        child.register_map(IStrategy, "x", StrategyB)

        result = child.resolve_map(IStrategy)
        assert result["x"].execute() == "B"


# ---------------------------------------------------------------------------
# Recipe serialization
# ---------------------------------------------------------------------------


class TestMapBindingRecipe:
    def test_map_binding_survives_recipe(self) -> None:
        c = Container()
        c.register_map(IStrategy, "a", StrategyA)
        c.register_map(IStrategy, "b", StrategyB)

        rebuilt = c.recipe.build()
        result = rebuilt.resolve_map(IStrategy)
        assert set(result.keys()) == {"a", "b"}

    def test_map_binding_cloudpickle_roundtrip(self) -> None:
        import cloudpickle

        c = Container()
        c.register_map(IStrategy, "a", StrategyA)

        data = cloudpickle.dumps(c.recipe)
        recipe = cloudpickle.loads(data)
        rebuilt = recipe.build()

        result = rebuilt.resolve_map(IStrategy)
        assert result["a"].execute() == "A"
