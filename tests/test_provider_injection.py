"""Tests for Provider[T] lazy injection."""

from typing import Annotated, Protocol, runtime_checkable

from autowire_di import Container, Named, ProviderWrapper, Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@runtime_checkable
class IDatabase(Protocol):
    def query(self) -> str: ...


class PostgresDatabase:
    def query(self) -> str:
        return "postgres"


class ExpensiveService:
    init_count = 0

    def __init__(self) -> None:
        ExpensiveService.init_count += 1

    def work(self) -> str:
        return "done"


class ScopedSession:
    pass


class DbProviderConsumer:
    def __init__(self, db_provider: ProviderWrapper[IDatabase]) -> None:
        self.db_provider = db_provider


class ExpensiveConsumer:
    def __init__(self, provider: ProviderWrapper[ExpensiveService]) -> None:
        self.provider = provider


class SingletonWithScopedProvider:
    def __init__(self, session_provider: ProviderWrapper[ScopedSession]) -> None:
        self.session_provider = session_provider


class NamedProviderConsumer:
    def __init__(
        self,
        primary: Annotated[ProviderWrapper[IDatabase], Named("primary")],
    ) -> None:
        self.primary = primary


# ---------------------------------------------------------------------------
# Basic Provider injection
# ---------------------------------------------------------------------------


class TestProviderInjection:
    def test_provider_injection_basic(self) -> None:
        c = Container()
        c.register(IDatabase, PostgresDatabase)
        svc = c.resolve(DbProviderConsumer)

        assert isinstance(svc.db_provider, ProviderWrapper)
        db = svc.db_provider.get()
        assert isinstance(db, PostgresDatabase)
        assert db.query() == "postgres"

    def test_provider_returns_new_instance_each_call(self) -> None:
        c = Container()
        c.register(IDatabase, PostgresDatabase)
        svc = c.resolve(DbProviderConsumer)

        db1 = svc.db_provider.get()
        db2 = svc.db_provider.get()
        assert db1 is not db2

    def test_provider_returns_singleton_when_scoped_singleton(self) -> None:
        c = Container()
        c.register(IDatabase, PostgresDatabase, scope=Scope.SINGLETON)
        svc = c.resolve(DbProviderConsumer)

        db1 = svc.db_provider.get()
        db2 = svc.db_provider.get()
        assert db1 is db2


# ---------------------------------------------------------------------------
# Lazy instantiation
# ---------------------------------------------------------------------------


class TestLazyInstantiation:
    def test_provider_defers_creation(self) -> None:
        ExpensiveService.init_count = 0

        c = Container()
        c.register(ExpensiveService)
        consumer = c.resolve(ExpensiveConsumer)

        assert ExpensiveService.init_count == 0
        consumer.provider.get()
        assert ExpensiveService.init_count == 1


# ---------------------------------------------------------------------------
# Cross-scope safety: Singleton holds Provider[Scoped]
# ---------------------------------------------------------------------------


class ScopedProviderConsumer:
    """Scoped service that holds a Provider to create transient instances."""
    def __init__(self, db_provider: ProviderWrapper[IDatabase]) -> None:
        self.db_provider = db_provider


class TestCrossScopeSafety:
    def test_scoped_service_with_provider_of_transient(self) -> None:
        """A scoped service can hold Provider[Transient] and get fresh
        instances on each call."""
        c = Container()
        c.register(IDatabase, PostgresDatabase)
        c.register(ScopedProviderConsumer, scope=Scope.SCOPED)

        with c.new_scope() as scope:
            svc = scope.resolve(ScopedProviderConsumer)
            db1 = svc.db_provider.get()
            db2 = svc.db_provider.get()
            assert isinstance(db1, PostgresDatabase)
            assert db1 is not db2

    def test_provider_in_scope_resolves_scoped_service(self) -> None:
        """Provider[ScopedSession] created within a scope can resolve
        scoped services."""
        c = Container()
        c.register(ScopedSession, scope=Scope.SCOPED)

        with c.new_scope() as scope:
            consumer = scope.resolve(SingletonWithScopedProvider)
            s1 = consumer.session_provider.get()
            s2 = consumer.session_provider.get()
            assert isinstance(s1, ScopedSession)
            assert s1 is s2  # same scope, same instance


# ---------------------------------------------------------------------------
# Provider with Named binding
# ---------------------------------------------------------------------------


class TestProviderWithNamed:
    def test_provider_with_named_via_annotated(self) -> None:
        c = Container()
        c.register(IDatabase, PostgresDatabase, name="primary")
        svc = c.resolve(NamedProviderConsumer)

        db = svc.primary.get()
        assert isinstance(db, PostgresDatabase)


# ---------------------------------------------------------------------------
# Provider repr
# ---------------------------------------------------------------------------


class TestProviderRepr:
    def test_repr(self) -> None:
        c = Container()
        c.register(IDatabase, PostgresDatabase)
        pw = ProviderWrapper(IDatabase, c)
        assert "IDatabase" in repr(pw)
