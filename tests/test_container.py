"""Comprehensive tests for the Container class of the Python DI framework."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pytest

from python_di import Container, ResolutionError, RegistrationError, Scope, ScopeNotActiveError


# ---------------------------------------------------------------------------
# Test Fixtures: Interfaces and Implementations
# ---------------------------------------------------------------------------


@runtime_checkable
class IRepository(Protocol):
    """Abstract interface (Protocol) for repositories."""

    def get(self, id: str) -> str:
        ...


class PostgresRepository:
    """Concrete implementation of IRepository."""

    def get(self, id: str) -> str:
        return f"postgres:{id}"


class InMemoryRepository:
    """Alternative implementation of IRepository."""

    def get(self, id: str) -> str:
        return f"memory:{id}"


class ConcreteService:
    """Concrete class with no dependencies."""

    pass


class ServiceWithDependency:
    """Concrete class that depends on IRepository via type hint."""

    def __init__(self, repo: IRepository) -> None:
        self.repo = repo


# ---------------------------------------------------------------------------
# Basic Registration and Resolution
# ---------------------------------------------------------------------------


class TestRegisterAndResolve:
    """Register interface -> implementation and resolve."""

    def test_register_interface_implementation_resolve(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)
        resolved = container.resolve(IRepository)
        assert isinstance(resolved, PostgresRepository)
        assert resolved.get("x") == "postgres:x"

    def test_register_concrete_self_binding(self) -> None:
        """Register concrete class as its own implementation (self-binding)."""
        container = Container()
        container.register(ConcreteService)  # No implementation = self-binding
        resolved = container.resolve(ConcreteService)
        assert isinstance(resolved, ConcreteService)

    def test_resolve_returns_new_instance_each_time_by_default(self) -> None:
        """Default scope is TRANSIENT."""
        container = Container()
        container.register(ConcreteService)
        a = container.resolve(ConcreteService)
        b = container.resolve(ConcreteService)
        assert a is not b


# ---------------------------------------------------------------------------
# ValueProvider (instance=)
# ---------------------------------------------------------------------------


class TestValueProvider:
    """Register with instance= (ValueProvider)."""

    def test_register_with_instance_returns_same_object(self) -> None:
        container = Container()
        pre_created = PostgresRepository()
        container.register(IRepository, instance=pre_created)
        resolved = container.resolve(IRepository)
        assert resolved is pre_created

    def test_register_concrete_with_instance(self) -> None:
        container = Container()
        obj = ConcreteService()
        container.register(ConcreteService, instance=obj)
        assert container.resolve(ConcreteService) is obj


# ---------------------------------------------------------------------------
# FactoryProvider (factory=)
# ---------------------------------------------------------------------------


class TestFactoryProvider:
    """Register with factory= (FactoryProvider)."""

    def test_register_with_factory_function(self) -> None:
        container = Container()
        container.register(IRepository, factory=lambda: InMemoryRepository())
        resolved = container.resolve(IRepository)
        assert isinstance(resolved, InMemoryRepository)
        assert resolved.get("y") == "memory:y"

    def test_factory_receives_auto_wired_dependencies(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)

        def make_service(repo: IRepository) -> ServiceWithDependency:
            return ServiceWithDependency(repo=repo)

        container.register(ServiceWithDependency, factory=make_service)
        resolved = container.resolve(ServiceWithDependency)
        assert isinstance(resolved.repo, PostgresRepository)


# ---------------------------------------------------------------------------
# Auto-wiring
# ---------------------------------------------------------------------------


class TestAutoWiring:
    """Unregistered concrete classes are auto-constructed from __init__ type hints."""

    def test_auto_wire_concrete_with_registered_dependency(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)
        # ServiceWithDependency not registered — auto-wired from type hints
        resolved = container.resolve(ServiceWithDependency)
        assert isinstance(resolved, ServiceWithDependency)
        assert isinstance(resolved.repo, PostgresRepository)

    def test_auto_wire_concrete_with_no_dependencies(self) -> None:
        container = Container()
        # ConcreteService has no __init__ params — just instantiate
        resolved = container.resolve(ConcreteService)
        assert isinstance(resolved, ConcreteService)

    def test_auto_wire_concrete_with_default_value_when_unregistered(self) -> None:
        """Parameter with default is used when resolution raises ResolutionError."""

        class ServiceWithDefault:
            def __init__(self, repo: IRepository = None) -> None:  # type: ignore[assignment]
                self.repo = repo

        container = Container()
        # IRepository not registered -> ResolutionError -> use default None
        resolved = container.resolve(ServiceWithDefault)
        assert resolved.repo is None


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------


class TestTransientScope:
    """Transient scope: each resolve creates new instance."""

    def test_transient_creates_new_instance_each_time(self) -> None:
        container = Container()
        container.register(ConcreteService, scope=Scope.TRANSIENT)
        a = container.resolve(ConcreteService)
        b = container.resolve(ConcreteService)
        assert a is not b


class TestSingletonScope:
    """Singleton scope: same instance returned."""

    def test_singleton_returns_same_instance(self) -> None:
        container = Container()
        container.register(ConcreteService, scope=Scope.SINGLETON)
        a = container.resolve(ConcreteService)
        b = container.resolve(ConcreteService)
        assert a is b

    def test_singleton_shared_across_scoped_resolution(self) -> None:
        container = Container()
        container.register(ConcreteService, scope=Scope.SINGLETON)
        with container.new_scope() as scope:
            a = scope.resolve(ConcreteService)
            b = scope.resolve(ConcreteService)
        c = container.resolve(ConcreteService)
        assert a is b is c


class TestScopedService:
    """Scoped services and ScopeNotActiveError."""

    def test_scoped_resolved_inside_scope(self) -> None:
        container = Container()
        container.register(ConcreteService, scope=Scope.SCOPED)
        with container.new_scope() as scope:
            a = scope.resolve(ConcreteService)
            b = scope.resolve(ConcreteService)
            assert a is b

    def test_scoped_different_instances_in_different_scopes(self) -> None:
        container = Container()
        container.register(ConcreteService, scope=Scope.SCOPED)
        with container.new_scope() as scope1:
            a = scope1.resolve(ConcreteService)
        with container.new_scope() as scope2:
            b = scope2.resolve(ConcreteService)
        assert a is not b

    def test_scoped_outside_scope_raises_scope_not_active_error(self) -> None:
        container = Container()
        container.register(ConcreteService, scope=Scope.SCOPED)
        with pytest.raises(ScopeNotActiveError) as exc_info:
            container.resolve(ConcreteService)
        assert "outside of an active scope" in str(exc_info.value)
        assert "new_scope" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Duplicate Registration and Override
# ---------------------------------------------------------------------------


class TestDuplicateRegistration:
    """Duplicate registration raises RegistrationError."""

    def test_duplicate_register_raises_registration_error(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)
        with pytest.raises(RegistrationError) as exc_info:
            container.register(IRepository, InMemoryRepository)
        assert "already registered" in str(exc_info.value)

    def test_duplicate_named_binding_raises_registration_error(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository, name="primary")
        with pytest.raises(RegistrationError):
            container.register(IRepository, InMemoryRepository, name="primary")


class TestOverride:
    """Override replaces existing binding."""

    def test_override_replaces_binding(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)
        container.override(IRepository, InMemoryRepository)
        resolved = container.resolve(IRepository)
        assert isinstance(resolved, InMemoryRepository)

    def test_override_with_factory(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)
        container.override(IRepository, factory=lambda: InMemoryRepository())
        resolved = container.resolve(IRepository)
        assert isinstance(resolved, InMemoryRepository)

    def test_override_with_instance(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)
        pre_created = InMemoryRepository()
        container.override(IRepository, instance=pre_created)
        assert container.resolve(IRepository) is pre_created

    def test_override_preserves_scope_when_not_specified(self) -> None:
        container = Container()
        container.register(ConcreteService, scope=Scope.SINGLETON)
        container.override(ConcreteService, InMemoryRepository)  # Different impl, same scope
        a = container.resolve(ConcreteService)
        b = container.resolve(ConcreteService)
        assert a is b  # Still singleton


# ---------------------------------------------------------------------------
# ResolutionError
# ---------------------------------------------------------------------------


class TestResolutionError:
    """Resolving unregistered abstract class raises ResolutionError."""

    def test_unregistered_protocol_raises_resolution_error(self) -> None:
        container = Container()
        with pytest.raises(ResolutionError) as exc_info:
            container.resolve(IRepository)
        assert "No binding registered" in str(exc_info.value)
        assert "IRepository" in str(exc_info.value)

    def test_unregistered_abstract_base_class_raises_resolution_error(self) -> None:
        from abc import ABC, abstractmethod

        class AbstractBase(ABC):
            @abstractmethod
            def method(self) -> None:
                pass

        container = Container()
        with pytest.raises(ResolutionError):
            container.resolve(AbstractBase)


# ---------------------------------------------------------------------------
# Named Bindings
# ---------------------------------------------------------------------------


class TestNamedBindings:
    """Register with name= for named bindings, resolve with name=."""

    def test_named_binding_register_and_resolve(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository, name="primary")
        container.register(IRepository, InMemoryRepository, name="secondary")
        primary = container.resolve(IRepository, name="primary")
        secondary = container.resolve(IRepository, name="secondary")
        assert isinstance(primary, PostgresRepository)
        assert isinstance(secondary, InMemoryRepository)
        assert primary is not secondary

    def test_resolve_without_name_uses_default_binding(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)  # default (no name)
        container.register(IRepository, InMemoryRepository, name="alt")
        resolved = container.resolve(IRepository)
        assert isinstance(resolved, PostgresRepository)

    def test_named_binding_not_found_raises_resolution_error(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)
        with pytest.raises(ResolutionError) as exc_info:
            container.resolve(IRepository, name="nonexistent")
        assert "name=" in str(exc_info.value) or "nonexistent" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Multi-bindings
# ---------------------------------------------------------------------------


class TestMultiBindings:
    """register_multi and resolve_multi."""

    def test_register_multi_resolve_multi(self) -> None:
        container = Container()
        container.register_multi(IRepository, PostgresRepository)
        container.register_multi(IRepository, InMemoryRepository)
        items = container.resolve_multi(IRepository)
        assert len(items) == 2
        types_seen = {type(x) for x in items}
        assert PostgresRepository in types_seen
        assert InMemoryRepository in types_seen

    def test_resolve_multi_empty_raises_resolution_error(self) -> None:
        container = Container()
        with pytest.raises(ResolutionError) as exc_info:
            container.resolve_multi(IRepository)
        assert "No multi-bindings" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Child Container
# ---------------------------------------------------------------------------


class TestChildContainer:
    """create_child creates child container."""

    def test_child_inherits_parent_bindings(self) -> None:
        parent = Container()
        parent.register(IRepository, PostgresRepository)
        child = parent.create_child()
        resolved = child.resolve(IRepository)
        assert isinstance(resolved, PostgresRepository)

    def test_child_can_override_parent_binding(self) -> None:
        parent = Container()
        parent.register(IRepository, PostgresRepository)
        child = parent.create_child()
        child.override(IRepository, InMemoryRepository)
        resolved = child.resolve(IRepository)
        assert isinstance(resolved, InMemoryRepository)

    def test_child_can_have_own_config(self) -> None:
        parent = Container()
        parent.set_config({"a": 1})
        child = parent.create_child(config={"b": 2})
        assert child.config == {"b": 2}


# ---------------------------------------------------------------------------
# Module Installation
# ---------------------------------------------------------------------------


class TestModuleInstallation:
    """install(module) installs a Module."""

    def test_install_module_configures_container(self) -> None:
        from python_di import Module

        class TestModule(Module):
            def configure(self, container: Container) -> None:
                container.register(IRepository, PostgresRepository)

        container = Container()
        container.install(TestModule())
        resolved = container.resolve(IRepository)
        assert isinstance(resolved, PostgresRepository)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """validate() validates all bindings."""

    def test_validate_succeeds_with_valid_bindings(self) -> None:
        container = Container()
        container.register(IRepository, PostgresRepository)
        container.validate()  # Should not raise

    def test_validate_does_not_raise_on_empty_container(self) -> None:
        container = Container()
        container.validate()  # Should not raise


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    """set_config sets config dict."""

    def test_set_config(self) -> None:
        container = Container()
        container.set_config({"db": {"host": "localhost"}})
        assert container.config == {"db": {"host": "localhost"}}


# ---------------------------------------------------------------------------
# Dispose
# ---------------------------------------------------------------------------


class TestDispose:
    """dispose() teardown singletons."""

    def test_dispose_clears_singletons(self) -> None:
        container = Container()
        container.register(ConcreteService, scope=Scope.SINGLETON)
        a = container.resolve(ConcreteService)
        container.dispose()
        b = container.resolve(ConcreteService)
        assert a is not b  # New instance after dispose
