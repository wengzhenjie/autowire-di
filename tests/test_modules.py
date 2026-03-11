"""Tests for the Module system."""

from __future__ import annotations

from python_di import Container, Module, Scope


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class Database:
    """Abstract database interface."""

    pass


class PostgresDatabase(Database):
    """Postgres implementation."""

    pass


class SqliteDatabase(Database):
    """SQLite implementation."""

    pass


class Cache:
    """Cache interface."""

    pass


class MemoryCache(Cache):
    """In-memory cache."""

    pass


class RedisCache(Cache):
    """Redis cache implementation."""

    pass


class Logger:
    """Logger service."""

    pass


class RequestContext:
    """Request-scoped context."""

    pass


class TransientHelper:
    """Transient helper service."""

    pass


# ---------------------------------------------------------------------------
# Basic module
# ---------------------------------------------------------------------------


class TestBasicModule:
    """Module registers bindings, container resolves them."""

    def test_module_registers_bindings(self) -> None:
        class InfraModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Database, PostgresDatabase, scope=Scope.SINGLETON)
                container.register(Cache, MemoryCache, scope=Scope.SINGLETON)

        container = Container()
        container.install(InfraModule())

        db = container.resolve(Database)
        cache = container.resolve(Cache)

        assert isinstance(db, PostgresDatabase)
        assert isinstance(cache, MemoryCache)

    def test_module_bindings_are_resolvable(self) -> None:
        class AppModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Logger, scope=Scope.TRANSIENT)

        container = Container()
        container.install(AppModule())

        logger1 = container.resolve(Logger)
        logger2 = container.resolve(Logger)

        assert isinstance(logger1, Logger)
        assert isinstance(logger2, Logger)
        assert logger1 is not logger2


# ---------------------------------------------------------------------------
# Multiple modules
# ---------------------------------------------------------------------------


class TestMultipleModules:
    """Install multiple modules, all bindings available."""

    def test_multiple_modules_all_bindings_available(self) -> None:
        class InfraModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Database, PostgresDatabase, scope=Scope.SINGLETON)

        class CacheModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Cache, MemoryCache, scope=Scope.SINGLETON)

        class LoggingModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Logger, scope=Scope.TRANSIENT)

        container = Container()
        container.install(InfraModule())
        container.install(CacheModule())
        container.install(LoggingModule())

        db = container.resolve(Database)
        cache = container.resolve(Cache)
        logger = container.resolve(Logger)

        assert isinstance(db, PostgresDatabase)
        assert isinstance(cache, MemoryCache)
        assert isinstance(logger, Logger)


# ---------------------------------------------------------------------------
# Module override
# ---------------------------------------------------------------------------


class TestModuleOverride:
    """Second module can override first module's bindings using container.override()."""

    def test_override_replaces_binding(self) -> None:
        class BaseModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Database, PostgresDatabase, scope=Scope.SINGLETON)
                container.register(Cache, MemoryCache, scope=Scope.SINGLETON)

        class TestOverridesModule(Module):
            def configure(self, container: Container) -> None:
                container.override(Database, SqliteDatabase, scope=Scope.SINGLETON)
                container.override(Cache, RedisCache, scope=Scope.SINGLETON)

        container = Container()
        container.install(BaseModule())
        container.install(TestOverridesModule())

        db = container.resolve(Database)
        cache = container.resolve(Cache)

        assert isinstance(db, SqliteDatabase)
        assert isinstance(cache, RedisCache)

    def test_override_preserves_scope_when_not_specified(self) -> None:
        class BaseModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Database, PostgresDatabase, scope=Scope.SINGLETON)

        class OverrideModule(Module):
            def configure(self, container: Container) -> None:
                container.override(Database, SqliteDatabase)

        container = Container()
        container.install(BaseModule())
        container.install(OverrideModule())

        db1 = container.resolve(Database)
        db2 = container.resolve(Database)

        assert isinstance(db1, SqliteDatabase)
        assert db1 is db2


# ---------------------------------------------------------------------------
# Module with different scopes
# ---------------------------------------------------------------------------


class TestModuleWithDifferentScopes:
    """Module registers singleton, transient, and scoped bindings."""

    def test_module_mixed_scopes(self) -> None:
        class MixedScopeModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Database, PostgresDatabase, scope=Scope.SINGLETON)
                container.register(TransientHelper, scope=Scope.TRANSIENT)
                container.register(RequestContext, scope=Scope.SCOPED)

        container = Container()
        container.install(MixedScopeModule())

        # Singleton: same instance
        db1 = container.resolve(Database)
        db2 = container.resolve(Database)
        assert db1 is db2

        # Transient: new each time
        t1 = container.resolve(TransientHelper)
        t2 = container.resolve(TransientHelper)
        assert t1 is not t2

        # Scoped: same within scope, different across scopes
        with container.new_scope() as scope1:
            r1 = scope1.resolve(RequestContext)
            r2 = scope1.resolve(RequestContext)
            assert r1 is r2

        with container.new_scope() as scope2:
            r3 = scope2.resolve(RequestContext)
            assert r3 is not r1
