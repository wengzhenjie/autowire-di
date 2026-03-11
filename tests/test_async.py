"""Tests for async support in the DI container."""

from __future__ import annotations

import pytest

from python_di import Container, Scope


class Pool:
    """Simple pool type for async factory tests."""

    def __init__(self) -> None:
        self.closed = False


class SyncService:
    """Sync service with no dependencies."""

    pass


class TestAsyncFactoryCoroutine:
    """Async factory (coroutine) resolved via async_resolve."""

    @pytest.mark.asyncio
    async def test_async_factory_resolved_via_async_resolve(self) -> None:
        async def create_pool() -> Pool:
            return Pool()

        container = Container()
        container.register(Pool, factory=create_pool, scope=Scope.TRANSIENT)
        pool = await container.async_resolve(Pool)
        assert isinstance(pool, Pool)
        assert pool.closed is False

    @pytest.mark.asyncio
    async def test_async_factory_in_async_scope(self) -> None:
        async def create_pool() -> Pool:
            return Pool()

        container = Container()
        container.register(Pool, factory=create_pool, scope=Scope.SCOPED)
        async with container.new_async_scope() as scope:
            pool = await scope.async_resolve(Pool)
            assert isinstance(pool, Pool)


class TestAsyncGeneratorFactory:
    """Async generator factory with teardown on scope exit."""

    @pytest.mark.asyncio
    async def test_async_generator_teardown_runs_on_scope_exit(self) -> None:
        async def create_pool() -> Pool:
            pool = Pool()
            yield pool
            pool.closed = True

        container = Container()
        container.register(Pool, factory=create_pool, scope=Scope.SCOPED)
        async with container.new_async_scope() as scope:
            pool = await scope.async_resolve(Pool)
            assert isinstance(pool, Pool)
            assert pool.closed is False
        assert pool.closed is True

    @pytest.mark.asyncio
    async def test_async_generator_same_instance_within_scope(self) -> None:
        async def create_pool() -> Pool:
            pool = Pool()
            yield pool
            pool.closed = True

        container = Container()
        container.register(Pool, factory=create_pool, scope=Scope.SCOPED)
        async with container.new_async_scope() as scope:
            p1 = await scope.async_resolve(Pool)
            p2 = await scope.async_resolve(Pool)
            assert p1 is p2


class TestAsyncScope:
    """Async scope context manager."""

    @pytest.mark.asyncio
    async def test_async_scope_async_resolve_works(self) -> None:
        container = Container()
        container.register(Pool, factory=lambda: Pool(), scope=Scope.SCOPED)
        async with container.new_async_scope() as scope:
            pool = await scope.async_resolve(Pool)
            assert isinstance(pool, Pool)

    @pytest.mark.asyncio
    async def test_async_scope_async_teardown_runs(self) -> None:
        teardown_ran: list[bool] = []

        async def create_pool() -> Pool:
            pool = Pool()
            yield pool
            teardown_ran.append(True)

        container = Container()
        container.register(Pool, factory=create_pool, scope=Scope.SCOPED)
        async with container.new_async_scope() as scope:
            await scope.async_resolve(Pool)
        assert teardown_ran == [True]


class TestSyncFactoryInAsyncScope:
    """Sync factories work in async scope."""

    @pytest.mark.asyncio
    async def test_sync_factory_resolved_in_async_scope(self) -> None:
        def create_pool() -> Pool:
            return Pool()

        container = Container()
        container.register(Pool, factory=create_pool, scope=Scope.SCOPED)
        async with container.new_async_scope() as scope:
            pool = await scope.async_resolve(Pool)
            assert isinstance(pool, Pool)

    @pytest.mark.asyncio
    async def test_sync_class_provider_in_async_scope(self) -> None:
        container = Container()
        container.register(SyncService)
        async with container.new_async_scope() as scope:
            svc = await scope.async_resolve(SyncService)
            assert isinstance(svc, SyncService)


class TestSingletonAsyncFactory:
    """Singleton async factory creates once, returns same instance."""

    @pytest.mark.asyncio
    async def test_singleton_async_factory_same_instance(self) -> None:
        create_count = 0

        async def create_pool() -> Pool:
            nonlocal create_count
            create_count += 1
            return Pool()

        container = Container()
        container.register(Pool, factory=create_pool, scope=Scope.SINGLETON)
        p1 = await container.async_resolve(Pool)
        p2 = await container.async_resolve(Pool)
        assert p1 is p2
        assert create_count == 1

    @pytest.mark.asyncio
    async def test_singleton_async_factory_in_async_scope(self) -> None:
        create_count = 0

        async def create_pool() -> Pool:
            nonlocal create_count
            create_count += 1
            return Pool()

        container = Container()
        container.register(Pool, factory=create_pool, scope=Scope.SINGLETON)
        async with container.new_async_scope() as scope:
            p1 = await scope.async_resolve(Pool)
            p2 = await scope.async_resolve(Pool)
            assert p1 is p2
            assert create_count == 1


class TestMixedSyncAndAsync:
    """Mixed sync and async dependencies resolve correctly in async scope."""

    @pytest.mark.asyncio
    async def test_sync_and_async_both_resolve_in_async_scope(self) -> None:
        """Sync and async services can both be resolved in the same async scope."""
        async def create_pool() -> Pool:
            return Pool()

        container = Container()
        container.register(SyncService)
        container.register(Pool, factory=create_pool, scope=Scope.SCOPED)
        async with container.new_async_scope() as scope:
            sync_svc = await scope.async_resolve(SyncService)
            pool = await scope.async_resolve(Pool)
            assert isinstance(sync_svc, SyncService)
            assert isinstance(pool, Pool)
