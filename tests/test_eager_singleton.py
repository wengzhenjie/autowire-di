"""Tests for eager singleton initialization and Recipe eager support."""

from __future__ import annotations

import pytest

from autowire_di import Container, Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class EagerService:
    init_count = 0

    def __init__(self) -> None:
        EagerService.init_count += 1


class LazyService:
    init_count = 0

    def __init__(self) -> None:
        LazyService.init_count += 1


class FailingService:
    def __init__(self) -> None:
        raise RuntimeError("init failed")


# ---------------------------------------------------------------------------
# Basic eager initialization
# ---------------------------------------------------------------------------


class TestEagerSingleton:
    def setup_method(self) -> None:
        EagerService.init_count = 0
        LazyService.init_count = 0

    def test_eager_singleton_created_on_initialize(self) -> None:
        c = Container()
        c.register(EagerService, scope=Scope.SINGLETON, eager=True)

        assert EagerService.init_count == 0
        c.initialize_singletons()
        assert EagerService.init_count == 1

    def test_non_eager_singleton_not_created(self) -> None:
        c = Container()
        c.register(LazyService, scope=Scope.SINGLETON, eager=False)

        c.initialize_singletons()
        assert LazyService.init_count == 0

    def test_mixed_eager_and_lazy(self) -> None:
        c = Container()
        c.register(EagerService, scope=Scope.SINGLETON, eager=True)
        c.register(LazyService, scope=Scope.SINGLETON, eager=False)

        c.initialize_singletons()
        assert EagerService.init_count == 1
        assert LazyService.init_count == 0

    def test_eager_singleton_same_instance_after_resolve(self) -> None:
        c = Container()
        c.register(EagerService, scope=Scope.SINGLETON, eager=True)

        c.initialize_singletons()
        svc = c.resolve(EagerService)
        assert EagerService.init_count == 1
        assert isinstance(svc, EagerService)

    def test_eager_transient_ignored(self) -> None:
        c = Container()
        c.register(EagerService, scope=Scope.TRANSIENT, eager=True)

        c.initialize_singletons()
        assert EagerService.init_count == 0

    def test_eager_failing_service_raises(self) -> None:
        c = Container()
        c.register(FailingService, scope=Scope.SINGLETON, eager=True)

        with pytest.raises(RuntimeError, match="init failed"):
            c.initialize_singletons()


# ---------------------------------------------------------------------------
# Async eager initialization
# ---------------------------------------------------------------------------


class TestAsyncEagerSingleton:
    def setup_method(self) -> None:
        EagerService.init_count = 0

    @pytest.mark.asyncio
    async def test_async_initialize_singletons(self) -> None:
        c = Container()
        c.register(EagerService, scope=Scope.SINGLETON, eager=True)

        await c.async_initialize_singletons()
        assert EagerService.init_count == 1


# ---------------------------------------------------------------------------
# Eager flag in Recipe
# ---------------------------------------------------------------------------


class TestEagerRecipe:
    def setup_method(self) -> None:
        EagerService.init_count = 0

    def test_eager_flag_preserved_in_recipe(self) -> None:
        c = Container()
        c.register(EagerService, scope=Scope.SINGLETON, eager=True)

        rebuilt = c.recipe.build()
        rebuilt.initialize_singletons()
        assert EagerService.init_count == 1

    def test_eager_flag_cloudpickle_roundtrip(self) -> None:
        import cloudpickle

        c = Container()
        c.register(EagerService, scope=Scope.SINGLETON, eager=True)

        data = cloudpickle.dumps(c.recipe)
        recipe = cloudpickle.loads(data)
        rebuilt = recipe.build()
        rebuilt.initialize_singletons()
        assert EagerService.init_count == 1
