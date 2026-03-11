"""Advanced feature tests: named bindings, multi-bindings, child containers,
config injection, and override mechanics."""

from __future__ import annotations

from typing import Annotated, Protocol, runtime_checkable

import pytest

from autowire_di import (
    Container,
    Module,
    Named,
    Inject,
    Scope,
    RegistrationError,
    ResolutionError,
)


# ---------------------------------------------------------------------------
# Fixture types
# ---------------------------------------------------------------------------


@runtime_checkable
class Cache(Protocol):
    def get(self, key: str) -> str | None: ...


class RedisCache:
    def get(self, key: str) -> str | None:
        return f"redis:{key}"


class MemoryCache:
    def get(self, key: str) -> str | None:
        return f"mem:{key}"


@runtime_checkable
class Validator(Protocol):
    def validate(self, value: str) -> bool: ...


class LengthValidator:
    def validate(self, value: str) -> bool:
        return len(value) > 0


class FormatValidator:
    def validate(self, value: str) -> bool:
        return value.isalpha()


class PatternValidator:
    def validate(self, value: str) -> bool:
        return value.startswith("x")


# ---------------------------------------------------------------------------
# Named bindings
# ---------------------------------------------------------------------------


class TestNamedBindings:
    def test_resolve_named_binding(self) -> None:
        c = Container()
        c.register(Cache, RedisCache, name="primary")
        c.register(Cache, MemoryCache, name="fallback")

        primary = c.resolve(Cache, name="primary")
        fallback = c.resolve(Cache, name="fallback")

        assert isinstance(primary, RedisCache)
        assert isinstance(fallback, MemoryCache)

    def test_named_binding_via_annotated(self) -> None:
        class Service:
            def __init__(
                self,
                primary: Annotated[Cache, Named("primary")],
                fallback: Annotated[Cache, Named("fallback")],
            ):
                self.primary = primary
                self.fallback = fallback

        c = Container()
        c.register(Cache, RedisCache, name="primary")
        c.register(Cache, MemoryCache, name="fallback")

        svc = c.resolve(Service)
        assert isinstance(svc.primary, RedisCache)
        assert isinstance(svc.fallback, MemoryCache)

    def test_missing_named_binding_raises(self) -> None:
        c = Container()
        c.register(Cache, RedisCache, name="primary")

        with pytest.raises(ResolutionError):
            c.resolve(Cache, name="nonexistent")


# ---------------------------------------------------------------------------
# Multi-bindings
# ---------------------------------------------------------------------------


class TestMultiBindings:
    def test_resolve_multi(self) -> None:
        c = Container()
        c.register_multi(Validator, LengthValidator)
        c.register_multi(Validator, FormatValidator)
        c.register_multi(Validator, PatternValidator)

        validators = c.resolve_multi(Validator)
        assert len(validators) == 3
        assert isinstance(validators[0], LengthValidator)
        assert isinstance(validators[1], FormatValidator)
        assert isinstance(validators[2], PatternValidator)

    def test_multi_binding_via_list_type_hint(self) -> None:
        class ValidationService:
            def __init__(self, validators: list[Validator]):
                self.validators = validators

        c = Container()
        c.register_multi(Validator, LengthValidator)
        c.register_multi(Validator, FormatValidator)

        svc = c.resolve(ValidationService)
        assert len(svc.validators) == 2

    def test_multi_binding_empty_raises(self) -> None:
        c = Container()
        with pytest.raises(ResolutionError):
            c.resolve_multi(Validator)

    def test_multi_binding_in_scope(self) -> None:
        c = Container()
        c.register_multi(Validator, LengthValidator)
        c.register_multi(Validator, FormatValidator)

        with c.new_scope() as scope:
            validators = scope.resolve_multi(Validator)
            assert len(validators) == 2

    def test_child_inherits_multi_bindings(self) -> None:
        c = Container()
        c.register_multi(Validator, LengthValidator)

        child = c.create_child()
        child.register_multi(Validator, FormatValidator)

        validators = child.resolve_multi(Validator)
        assert len(validators) == 2


# ---------------------------------------------------------------------------
# Child containers
# ---------------------------------------------------------------------------


class TestChildContainers:
    def test_child_inherits_parent_bindings(self) -> None:
        parent = Container()
        parent.register(Cache, RedisCache, name="primary")

        child = parent.create_child()
        cache = child.resolve(Cache, name="primary")
        assert isinstance(cache, RedisCache)

    def test_child_override_does_not_affect_parent(self) -> None:
        parent = Container()
        parent.register(Cache, RedisCache, name="primary")

        child = parent.create_child()
        child.override(Cache, MemoryCache, name="primary")

        assert isinstance(child.resolve(Cache, name="primary"), MemoryCache)
        assert isinstance(parent.resolve(Cache, name="primary"), RedisCache)

    def test_child_inherits_parent_config(self) -> None:
        class Service:
            def __init__(self, port: Annotated[int, Inject(config="port")]):
                self.port = port

        parent = Container(config={"port": 8080})
        child = parent.create_child()

        svc = child.resolve(Service)
        assert svc.port == 8080

    def test_child_overrides_config(self) -> None:
        class Service:
            def __init__(self, port: Annotated[int, Inject(config="port")]):
                self.port = port

        parent = Container(config={"port": 8080})
        child = parent.create_child(config={"port": 9090})

        assert child.resolve(Service).port == 9090
        assert parent.resolve(Service).port == 8080

    def test_child_shares_parent_singletons(self) -> None:
        parent = Container()
        parent.register(RedisCache, scope=Scope.SINGLETON)

        child = parent.create_child()
        from_parent = parent.resolve(RedisCache)
        from_child = child.resolve(RedisCache)
        assert from_parent is from_child


# ---------------------------------------------------------------------------
# Config injection
# ---------------------------------------------------------------------------


class TestConfigInjection:
    def test_simple_config(self) -> None:
        class Service:
            def __init__(self, host: Annotated[str, Inject(config="host")]):
                self.host = host

        c = Container(config={"host": "localhost"})
        assert c.resolve(Service).host == "localhost"

    def test_nested_config(self) -> None:
        class Service:
            def __init__(self, port: Annotated[int, Inject(config="db.port")]):
                self.port = port

        c = Container(config={"db": {"port": 5432}})
        assert c.resolve(Service).port == 5432

    def test_deeply_nested_config(self) -> None:
        class Service:
            def __init__(self, val: Annotated[str, Inject(config="a.b.c.d")]):
                self.val = val

        c = Container(config={"a": {"b": {"c": {"d": "deep"}}}})
        assert c.resolve(Service).val == "deep"

    def test_missing_config_raises(self) -> None:
        class Service:
            def __init__(self, host: Annotated[str, Inject(config="missing")]):
                self.host = host

        c = Container(config={})
        with pytest.raises(ResolutionError, match="missing"):
            c.resolve(Service)

    def test_no_config_provided_raises(self) -> None:
        class Service:
            def __init__(self, host: Annotated[str, Inject(config="host")]):
                self.host = host

        c = Container()
        with pytest.raises(ResolutionError, match="No configuration"):
            c.resolve(Service)

    def test_set_config_after_creation(self) -> None:
        class Service:
            def __init__(self, host: Annotated[str, Inject(config="host")]):
                self.host = host

        c = Container()
        c.set_config({"host": "example.com"})
        assert c.resolve(Service).host == "example.com"


# ---------------------------------------------------------------------------
# Override mechanics
# ---------------------------------------------------------------------------


class TestOverride:
    def test_override_replaces_binding(self) -> None:
        c = Container()
        c.register(Cache, RedisCache, name="main")
        c.override(Cache, MemoryCache, name="main")

        assert isinstance(c.resolve(Cache, name="main"), MemoryCache)

    def test_override_preserves_scope(self) -> None:
        c = Container()
        c.register(Cache, RedisCache, name="main", scope=Scope.SINGLETON)
        c.override(Cache, MemoryCache, name="main")

        c1 = c.resolve(Cache, name="main")
        c2 = c.resolve(Cache, name="main")
        assert c1 is c2  # scope preserved as SINGLETON

    def test_override_can_change_scope(self) -> None:
        c = Container()
        c.register(Cache, RedisCache, name="main", scope=Scope.SINGLETON)
        c.override(Cache, MemoryCache, name="main", scope=Scope.TRANSIENT)

        c1 = c.resolve(Cache, name="main")
        c2 = c.resolve(Cache, name="main")
        assert c1 is not c2

    def test_override_with_instance(self) -> None:
        c = Container()
        c.register(Cache, RedisCache, name="main")

        specific = MemoryCache()
        c.override(Cache, instance=specific, name="main")
        assert c.resolve(Cache, name="main") is specific

    def test_override_with_factory(self) -> None:
        c = Container()
        c.register(Cache, RedisCache, name="main")

        c.override(Cache, factory=lambda: MemoryCache(), name="main")
        assert isinstance(c.resolve(Cache, name="main"), MemoryCache)


# ---------------------------------------------------------------------------
# Registration errors
# ---------------------------------------------------------------------------


class TestRegistrationErrors:
    def test_duplicate_raises(self) -> None:
        c = Container()
        c.register(Cache, RedisCache, name="main")
        with pytest.raises(RegistrationError):
            c.register(Cache, MemoryCache, name="main")

    def test_multiple_providers_raises(self) -> None:
        c = Container()
        with pytest.raises(ValueError, match="at most one"):
            c.register(Cache, RedisCache, factory=lambda: MemoryCache())

    def test_abstract_without_impl_raises(self) -> None:
        from abc import ABC, abstractmethod

        class AbstractRepo(ABC):
            @abstractmethod
            def save(self) -> None: ...

        c = Container()
        with pytest.raises(ValueError, match="abstract"):
            c.register(AbstractRepo)


# ---------------------------------------------------------------------------
# Integration: Module + Config + Named + Scoped
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_stack(self) -> None:
        class AppModule(Module):
            def configure(self, container: Container) -> None:
                container.register(Cache, RedisCache, name="primary", scope=Scope.SINGLETON)
                container.register(Cache, MemoryCache, name="fallback", scope=Scope.TRANSIENT)

        class OrderService:
            def __init__(
                self,
                primary: Annotated[Cache, Named("primary")],
                fallback: Annotated[Cache, Named("fallback")],
                timeout: Annotated[int, Inject(config="order.timeout")],
            ):
                self.primary = primary
                self.fallback = fallback
                self.timeout = timeout

        c = Container(config={"order": {"timeout": 30}})
        c.install(AppModule())

        svc = c.resolve(OrderService)
        assert isinstance(svc.primary, RedisCache)
        assert isinstance(svc.fallback, MemoryCache)
        assert svc.timeout == 30

        # Singleton check
        svc2 = c.resolve(OrderService)
        assert svc.primary is svc2.primary
        assert svc.fallback is not svc2.fallback
