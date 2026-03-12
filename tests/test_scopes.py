"""Tests for scoped lifecycle management."""

from __future__ import annotations

import pytest

import asyncio
from typing import Protocol, runtime_checkable

from autowire_di import Container, Scope, ScopeNotActiveError


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class Session:
    """Simple session type for scoped tests."""

    def __init__(self, id: str = "default") -> None:
        self.id = id


class ScopedService:
    """A service with scoped lifecycle."""

    pass


class SingletonService:
    """A service with singleton lifecycle."""

    pass


class TransientService:
    """A service with transient lifecycle."""

    pass


class ScopedDepA:
    """Scoped service A for nested wiring."""

    pass


class ScopedDepB:
    """Scoped service B depending on ScopedDepA."""

    def __init__(self, dep_a: ScopedDepA) -> None:
        self.dep_a = dep_a


# ---------------------------------------------------------------------------
# Scoped service: same instance within scope, different across scopes
# ---------------------------------------------------------------------------


class TestScopedServiceLifecycle:
    """Same instance within one scope, different across scopes."""

    def test_same_instance_within_scope(self) -> None:
        container = Container()
        container.register(ScopedService, scope=Scope.SCOPED)

        with container.new_scope() as scope:
            a = scope.resolve(ScopedService)
            b = scope.resolve(ScopedService)
            assert a is b

    def test_different_instances_across_scopes(self) -> None:
        container = Container()
        container.register(ScopedService, scope=Scope.SCOPED)

        with container.new_scope() as scope1:
            a = scope1.resolve(ScopedService)
        with container.new_scope() as scope2:
            b = scope2.resolve(ScopedService)
        assert a is not b


# ---------------------------------------------------------------------------
# Scoped + Singleton mix
# ---------------------------------------------------------------------------


class TestScopedSingletonMix:
    """Singleton is shared across scopes, scoped is not."""

    def test_singleton_shared_across_scopes(self) -> None:
        container = Container()
        container.register(SingletonService, scope=Scope.SINGLETON)
        container.register(ScopedService, scope=Scope.SCOPED)

        with container.new_scope() as scope1:
            singleton1 = scope1.resolve(SingletonService)
            scoped1 = scope1.resolve(ScopedService)
        with container.new_scope() as scope2:
            singleton2 = scope2.resolve(SingletonService)
            scoped2 = scope2.resolve(ScopedService)

        assert singleton1 is singleton2
        assert scoped1 is not scoped2


# ---------------------------------------------------------------------------
# Scoped + Transient mix
# ---------------------------------------------------------------------------


class TestScopedTransientMix:
    """Transient creates new instance each time even within scope."""

    def test_transient_new_each_time_within_scope(self) -> None:
        container = Container()
        container.register(TransientService, scope=Scope.TRANSIENT)
        container.register(ScopedService, scope=Scope.SCOPED)

        with container.new_scope() as scope:
            t1 = scope.resolve(TransientService)
            t2 = scope.resolve(TransientService)
            s1 = scope.resolve(ScopedService)
            s2 = scope.resolve(ScopedService)

        assert t1 is not t2
        assert s1 is s2


# ---------------------------------------------------------------------------
# Teardown on scope exit (generator factory)
# ---------------------------------------------------------------------------


class TestTeardownOnScopeExit:
    """Factory using generator (yield) runs cleanup on scope exit."""

    def test_generator_factory_teardown_on_scope_exit(self) -> None:
        created: list[Session] = []
        destroyed: list[Session] = []

        def create_session() -> Session:
            s = Session()
            created.append(s)
            yield s
            destroyed.append(s)

        container = Container()
        container.register(Session, factory=create_session, scope=Scope.SCOPED)

        with container.new_scope() as scope:
            s = scope.resolve(Session)
            assert s in created
            assert s not in destroyed

        assert s in destroyed
        assert len(created) == 1
        assert len(destroyed) == 1


# ---------------------------------------------------------------------------
# Multiple concurrent scopes
# ---------------------------------------------------------------------------


class TestMultipleScopes:
    """Two concurrent scopes each have their own instances."""

    def test_concurrent_scopes_independent_instances(self) -> None:
        container = Container()
        container.register(ScopedService, scope=Scope.SCOPED)

        with container.new_scope() as scope1:
            with container.new_scope() as scope2:
                a = scope1.resolve(ScopedService)
                b = scope2.resolve(ScopedService)
                assert a is not b
            # scope2 disposed, scope1 still active
            a2 = scope1.resolve(ScopedService)
            assert a is a2


# ---------------------------------------------------------------------------
# Resolving scoped outside scope
# ---------------------------------------------------------------------------


class TestResolveScopedOutsideScope:
    """Resolving scoped service outside scope raises ScopeNotActiveError."""

    def test_resolve_scoped_directly_on_container_raises(self) -> None:
        container = Container()
        container.register(ScopedService, scope=Scope.SCOPED)

        with pytest.raises(ScopeNotActiveError) as exc_info:
            container.resolve(ScopedService)

        assert "ScopedService" in str(exc_info.value)
        assert "scope" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Nested auto-wiring in scope
# ---------------------------------------------------------------------------


class TestNestedScopedAutoWiring:
    """Scoped service depending on another scoped service."""

    def test_scoped_depends_on_scoped_same_scope(self) -> None:
        container = Container()
        container.register(ScopedDepA, scope=Scope.SCOPED)
        container.register(ScopedDepB, scope=Scope.SCOPED)

        with container.new_scope() as scope:
            b1 = scope.resolve(ScopedDepB)
            b2 = scope.resolve(ScopedDepB)
            a1 = scope.resolve(ScopedDepA)

        assert b1 is b2
        assert b1.dep_a is a1
        assert b1.dep_a is b2.dep_a


# ---------------------------------------------------------------------------
# Resolution mixin deduplication
# ---------------------------------------------------------------------------


@runtime_checkable
class ICache(Protocol):
    def get(self, key: str) -> str | None: ...


class RedisCache:
    def get(self, key: str) -> str | None:
        return f"redis:{key}"


class MemoryCache:
    def get(self, key: str) -> str | None:
        return f"mem:{key}"


class DbPool:
    def __init__(self) -> None:
        self.connected = True


class TestResolutionMixinDedup:
    def test_container_and_scoped_resolve_same_singleton(self) -> None:
        c = Container()
        c.register(DbPool, scope=Scope.SINGLETON)

        pool_from_container = c.resolve(DbPool)
        with c.new_scope() as scope:
            pool_from_scope = scope.resolve(DbPool)
        assert pool_from_container is pool_from_scope

    def test_scoped_resolve_multi(self) -> None:
        c = Container()
        c.register_multi(ICache, RedisCache)
        c.register_multi(ICache, MemoryCache)

        with c.new_scope() as scope:
            caches = scope.resolve_multi(ICache)
            assert len(caches) == 2
            assert any(isinstance(x, RedisCache) for x in caches)
            assert any(isinstance(x, MemoryCache) for x in caches)

    def test_scoped_resolve_map(self) -> None:
        c = Container()
        c.register_map(ICache, "redis", RedisCache)
        c.register_map(ICache, "memory", MemoryCache)

        with c.new_scope() as scope:
            caches = scope.resolve_map(ICache)
            assert set(caches.keys()) == {"redis", "memory"}

    def test_async_resolve_through_mixin(self) -> None:
        async def run() -> None:
            c = Container()
            c.register(DbPool, scope=Scope.SINGLETON)
            pool = await c.async_resolve(DbPool)
            assert isinstance(pool, DbPool)

        asyncio.run(run())
