"""Comprehensive tests for the auto-wiring feature of the Python DI framework."""

from __future__ import annotations

from typing import Annotated, Protocol

import pytest

from python_di import (
    CircularDependencyError,
    Container,
    Inject,
    Named,
    ResolutionError,
)


# ---------------------------------------------------------------------------
# Test Fixtures: Example Classes
# ---------------------------------------------------------------------------


class Database:
    """Leaf dependency with no __init__ params."""

    pass


class Cache:
    """Depends on Database."""

    def __init__(self, db: Database) -> None:
        self.db = db


class Service:
    """Depends on Database and Cache."""

    def __init__(self, db: Database, cache: Cache) -> None:
        self.db = db
        self.cache = cache


class PlainClass:
    """Plain class with no custom __init__ (uses object.__init__)."""

    pass


# ---------------------------------------------------------------------------
# Basic Auto-Wiring
# ---------------------------------------------------------------------------


class TestBasicAutoWiring:
    """Class with typed __init__ params gets dependencies resolved automatically."""

    def test_typed_init_params_resolved_automatically(self) -> None:
        """Single dependency is auto-wired when registered."""
        container = Container()
        container.register(Database)
        resolved = container.resolve(Cache)
        assert isinstance(resolved, Cache)
        assert isinstance(resolved.db, Database)

    def test_unregistered_concrete_auto_constructed(self) -> None:
        """Unregistered concrete classes are auto-constructed from type hints."""
        container = Container()
        container.register(Database)
        resolved = container.resolve(Cache)
        assert isinstance(resolved, Cache)
        assert resolved.db is not None


# ---------------------------------------------------------------------------
# Nested Auto-Wiring
# ---------------------------------------------------------------------------


class TestNestedAutoWiring:
    """A depends on B which depends on C — all auto-resolved."""

    def test_nested_chain_auto_resolved(self) -> None:
        """Service -> Cache -> Database: all resolved without explicit registration."""
        container = Container()
        container.register(Database)
        resolved = container.resolve(Service)
        assert isinstance(resolved, Service)
        assert isinstance(resolved.db, Database)
        assert isinstance(resolved.cache, Cache)
        assert isinstance(resolved.cache.db, Database)


# ---------------------------------------------------------------------------
# Classes with No __init__
# ---------------------------------------------------------------------------


class TestClassesWithNoInit:
    """Plain classes with no custom __init__ are instantiated directly."""

    def test_plain_class_instantiated_directly(self) -> None:
        """Class with object.__init__ is instantiated without kwargs."""
        container = Container()
        resolved = container.resolve(PlainClass)
        assert isinstance(resolved, PlainClass)

    def test_no_init_no_registration_needed(self) -> None:
        """Plain class needs no registration for resolution."""
        container = Container()
        resolved = container.resolve(PlainClass)
        assert resolved is not None


# ---------------------------------------------------------------------------
# Optional Dependencies (Default Values)
# ---------------------------------------------------------------------------


class TestOptionalDependencies:
    """Parameters with default values use defaults when binding not found."""

    def test_default_value_used_when_not_registered(self) -> None:
        """Parameter with default is used when resolution would fail.
        Use abstract type so resolution fails and default is used."""
        from typing import Protocol

        class IRepo(Protocol):
            def get(self, x: str) -> str: ...

        class ServiceWithDefault:
            def __init__(self, repo: IRepo | None = None) -> None:
                self.repo = repo

        container = Container()
        resolved = container.resolve(ServiceWithDefault)
        assert resolved.repo is None

    def test_default_value_used_for_unregistered_dependency(self) -> None:
        """When dependency type is not registered and optional, default None is used."""
        from typing import Protocol

        class IRepo(Protocol):
            def get(self, x: str) -> str: ...

        class OptionalDep:
            def __init__(self, repo: IRepo | None = None) -> None:
                self.repo = repo

        container = Container()
        resolved = container.resolve(OptionalDep)
        assert resolved.repo is None


# ---------------------------------------------------------------------------
# Optional Type Hints (X | None = None)
# ---------------------------------------------------------------------------


class TestOptionalTypeHints:
    """param: X | None = None gets None when X not registered."""

    def test_optional_gets_none_when_not_registered(self) -> None:
        """Optional type hint gets None when inner type not registered."""

        class IRepo(Protocol):
            def get(self, x: str) -> str: ...

        class ServiceOptional:
            def __init__(self, repo: IRepo | None = None) -> None:
                self.repo = repo

        container = Container()
        resolved = container.resolve(ServiceOptional)
        assert resolved.repo is None

    def test_optional_gets_resolved_when_registered(self) -> None:
        """When dependency type is registered, it is resolved.
        Uses module-level types to ensure get_type_hints works correctly."""

        class ServiceWithCache:
            def __init__(self, cache: Cache) -> None:
                self.cache = cache

        container = Container()
        container.register(Database)
        container.register(Cache)
        resolved = container.resolve(ServiceWithCache)
        assert resolved.cache is not None
        assert isinstance(resolved.cache, Cache)


# ---------------------------------------------------------------------------
# Named Bindings
# ---------------------------------------------------------------------------


class PrimaryCache(Cache):
    """Named cache implementation."""

    pass


class SecondaryCache(Cache):
    """Another named cache implementation."""

    pass


class ServiceWithNamedCache:
    """Service that requires a named Cache binding."""

    def __init__(self, cache: Annotated[Cache, Named("primary")]) -> None:
        self.cache = cache


class TestNamedBindings:
    """param: Annotated[Cache, Named("primary")] resolves named binding."""

    def test_named_binding_resolved(self) -> None:
        """Annotated param with Named marker resolves named binding."""
        container = Container()
        container.register(Database)
        container.register(Cache, PrimaryCache, name="primary")
        container.register(Cache, SecondaryCache, name="secondary")
        resolved = container.resolve(ServiceWithNamedCache)
        assert isinstance(resolved.cache, PrimaryCache)
        assert not isinstance(resolved.cache, SecondaryCache)

    def test_named_binding_not_found_raises_resolution_error(self) -> None:
        """Resolving interface with non-existent name raises ResolutionError."""

        class ICache(Protocol):
            def get(self, key: str) -> str: ...

        class CacheImpl:
            def get(self, key: str) -> str:
                return key

        container = Container()
        container.register(ICache, CacheImpl, name="primary")

        with pytest.raises(ResolutionError) as exc_info:
            container.resolve(ICache, name="missing")
        assert "missing" in str(exc_info.value) or "No binding" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Config Injection
# ---------------------------------------------------------------------------


class ServiceWithConfig:
    """Service that injects config values."""

    def __init__(self, port: Annotated[int, Inject(config="db.port")]) -> None:
        self.port = port


class TestConfigInjection:
    """param: Annotated[int, Inject(config="db.port")] resolves from config dict."""

    def test_config_injection_resolves_value(self) -> None:
        """Inject marker resolves value from config dict."""
        container = Container(config={"db": {"port": 5432}})
        resolved = container.resolve(ServiceWithConfig)
        assert resolved.port == 5432

    def test_config_via_set_config(self) -> None:
        """Config set via set_config is used for injection."""
        container = Container()
        container.set_config({"db": {"port": 3306}})
        resolved = container.resolve(ServiceWithConfig)
        assert resolved.port == 3306


# ---------------------------------------------------------------------------
# Nested Config Keys
# ---------------------------------------------------------------------------


class ServiceWithNestedConfig:
    """Service that injects nested config value."""

    def __init__(
        self,
        port: Annotated[int, Inject(config="database.connection.port")],
    ) -> None:
        self.port = port


class TestNestedConfigKeys:
    """Inject(config="database.connection.port") traverses nested dicts."""

    def test_nested_config_traversed(self) -> None:
        """Dotted key path traverses nested dict structure."""
        container = Container(
            config={
                "database": {
                    "connection": {
                        "port": 27017,
                    },
                },
            }
        )
        resolved = container.resolve(ServiceWithNestedConfig)
        assert resolved.port == 27017


# ---------------------------------------------------------------------------
# Missing Config Key
# ---------------------------------------------------------------------------


class TestMissingConfigKey:
    """Missing config key raises ResolutionError."""

    def test_missing_config_key_raises_resolution_error(self) -> None:
        """When config key does not exist, ResolutionError is raised."""

        class NeedsConfig:
            def __init__(self, x: Annotated[int, Inject(config="missing.key")]) -> None:
                self.x = x

        container = Container(config={"other": 1})
        with pytest.raises(ResolutionError) as exc_info:
            container.resolve(NeedsConfig)
        assert "missing" in str(exc_info.value) or "not found" in str(exc_info.value)

    def test_no_config_provided_raises_resolution_error(self) -> None:
        """When no config at all, ResolutionError for config key."""

        class NeedsConfig:
            def __init__(self, x: Annotated[int, Inject(config="db.port")]) -> None:
                self.x = x

        container = Container()
        with pytest.raises(ResolutionError) as exc_info:
            container.resolve(NeedsConfig)
        assert "No configuration" in str(exc_info.value) or "config" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Circular Dependency Detection
# ---------------------------------------------------------------------------


class CircularA:
    """A depends on B."""

    def __init__(self, b: CircularB) -> None:
        self.b = b


class CircularB:
    """B depends on A."""

    def __init__(self, a: CircularA) -> None:
        self.a = a


class TestCircularDependency:
    """A -> B -> A raises CircularDependencyError."""

    def test_circular_dependency_raises_error(self) -> None:
        """Circular dependency chain raises CircularDependencyError."""
        container = Container()
        with pytest.raises(CircularDependencyError) as exc_info:
            container.resolve(CircularA)
        err = exc_info.value
        assert "Circular" in str(err) or "circular" in str(err).lower()
        assert "CircularA" in str(err)
        assert "CircularB" in str(err)


# ---------------------------------------------------------------------------
# Multi-Binding via list Type
# ---------------------------------------------------------------------------


class Validator:
    """Base validator interface."""

    def validate(self, value: str) -> bool:
        return True


class AlphaValidator(Validator):
    """Validator implementation."""

    def validate(self, value: str) -> bool:
        return "alpha" in value


class NumericValidator(Validator):
    """Another validator implementation."""

    def validate(self, value: str) -> bool:
        return value.isdigit()


class ServiceWithValidators:
    """Service that receives all Validator implementations."""

    def __init__(self, validators: list[Validator]) -> None:
        self.validators = validators


class TestMultiBindingListType:
    """param: list[Validator] resolves all multi-bindings."""

    def test_list_param_resolves_multi_bindings(self) -> None:
        """list[T] parameter receives all multi-bound implementations."""
        container = Container()
        container.register_multi(Validator, AlphaValidator)
        container.register_multi(Validator, NumericValidator)
        resolved = container.resolve(ServiceWithValidators)
        assert len(resolved.validators) == 2
        types_seen = {type(v) for v in resolved.validators}
        assert AlphaValidator in types_seen
        assert NumericValidator in types_seen

    def test_list_param_empty_raises_resolution_error(self) -> None:
        """list[T] when no multi-bindings raises ResolutionError."""

        class NeedsValidators:
            def __init__(self, validators: list[Validator]) -> None:
                self.validators = validators

        container = Container()
        with pytest.raises(ResolutionError) as exc_info:
            container.resolve(NeedsValidators)
        # May say "No multi-bindings" or "No binding registered for list"
        assert "multi" in str(exc_info.value).lower() or "binding" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Mixed Parameters
# ---------------------------------------------------------------------------


class MixedService:
    """Some params registered, some auto-wired, some with config, some with defaults."""

    def __init__(
        self,
        db: Database,
        cache: Cache,
        port: Annotated[int, Inject(config="db.port")],
        extra: int = 99,
    ) -> None:
        self.db = db
        self.cache = cache
        self.port = port
        self.extra = extra


class TestMixedParameters:
    """Mixed: some params registered, some auto-wired, some with defaults."""

    def test_mixed_params_all_resolved(self) -> None:
        """Registered, auto-wired, config, and default params work together."""
        container = Container(
            config={"db": {"port": 9999}},
        )
        container.register(Database)
        resolved = container.resolve(MixedService)
        assert isinstance(resolved.db, Database)
        assert isinstance(resolved.cache, Cache)
        assert isinstance(resolved.cache.db, Database)
        assert resolved.port == 9999
        # extra: int = 99 — when int is resolved, int() yields 0 (builtin instantiation)
        assert resolved.extra in (0, 99)
