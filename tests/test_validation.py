"""Tests for container startup validation."""

from __future__ import annotations

from typing import Protocol

import pytest

from python_di import (
    CircularDependencyError,
    Container,
    ResolutionError,
    Scope,
    ScopeMismatchError,
    ValidationError,
)


# ---------------------------------------------------------------------------
# Protocol and concrete types for validation tests
# ---------------------------------------------------------------------------


class Repository(Protocol):
    """Abstract repository interface."""

    def save(self) -> None: ...


class Cache(Protocol):
    """Abstract cache interface."""

    def get(self, key: str) -> str | None: ...


class OrderService:
    """Service depending on Repository (abstract, must be registered)."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo


class ServiceA:
    """Part of circular dependency: A -> B -> A."""

    def __init__(self, b: ServiceB) -> None:
        self.b = b


class ServiceB:
    """Part of circular dependency: A -> B -> A."""

    def __init__(self, a: ServiceA) -> None:
        self.a = a


class ScopedDep:
    """Scoped service (shorter-lived than singleton)."""

    pass


class SingletonConsumer:
    """Singleton that depends on Scoped — scope mismatch."""

    def __init__(self, dep: ScopedDep) -> None:
        self.dep = dep


class ServiceWithOptionalDep:
    """Service with optional dependency (has default)."""

    def __init__(self, cache: Cache | None = None) -> None:
        self.cache = cache


class ConcreteHelper:
    """Concrete class, auto-wirable without registration."""

    pass


class ServiceWithConcreteDep:
    """Service depending on unregistered concrete class."""

    def __init__(self, helper: ConcreteHelper) -> None:
        self.helper = helper


class ValidService:
    """Service with all deps satisfied."""

    def __init__(self, helper: ConcreteHelper) -> None:
        self.helper = helper


class PostgresRepository:
    """Concrete implementation of Repository."""

    def save(self) -> None:
        pass


class TestValidContainer:
    """Valid container passes validation."""

    def test_all_deps_satisfied_no_error(self) -> None:
        """Container with all dependencies satisfied validates successfully."""
        container = Container()
        container.register(Repository, PostgresRepository)
        container.register(OrderService)
        container.validate()  # Should not raise

    def test_concrete_only_also_valid(self) -> None:
        """Container with only concrete auto-wirable deps is valid."""
        container = Container()
        container.register(ValidService)
        container.validate()  # Should not raise


class TestMissingBinding:
    """Missing binding detected for unregistered abstract type."""

    def test_missing_binding_raises_validation_error(self) -> None:
        """Service depending on unregistered abstract type fails validation."""
        container = Container()
        container.register(OrderService)
        # Repository is not registered
        with pytest.raises(ValidationError) as exc_info:
            container.validate()
        assert len(exc_info.value.errors) >= 1
        assert any(
            isinstance(e, ResolutionError) and "Repository" in str(e)
            for e in exc_info.value.errors
        )


class TestCircularDependency:
    """Circular dependency detected."""

    def test_circular_dependency_detected(self) -> None:
        """A -> B -> A cycle is detected."""
        container = Container()
        container.register(ServiceA)
        container.register(ServiceB)
        with pytest.raises(ValidationError) as exc_info:
            container.validate()
        assert len(exc_info.value.errors) >= 1
        assert any(
            isinstance(e, CircularDependencyError) for e in exc_info.value.errors
        )


class TestScopeMismatch:
    """Scope mismatch detected: longer-lived depends on shorter-lived."""

    def test_singleton_depends_on_scoped_raises(self) -> None:
        """Singleton depending on Scoped service fails validation."""
        container = Container()
        container.register(ScopedDep, scope=Scope.SCOPED)
        container.register(SingletonConsumer, scope=Scope.SINGLETON)
        with pytest.raises(ValidationError) as exc_info:
            container.validate()
        assert len(exc_info.value.errors) >= 1
        assert any(
            isinstance(e, ScopeMismatchError) for e in exc_info.value.errors
        )


class TestMultipleErrors:
    """Multiple errors collected in one ValidationError."""

    def test_multiple_errors_collected(self) -> None:
        """Several validation problems reported together."""
        container = Container()
        container.register(OrderService)  # Missing Repository
        container.register(ServiceA)
        container.register(ServiceB)  # Circular A <-> B
        container.register(ScopedDep, scope=Scope.SCOPED)
        container.register(SingletonConsumer, scope=Scope.SINGLETON)  # Scope mismatch
        with pytest.raises(ValidationError) as exc_info:
            container.validate()
        errors = exc_info.value.errors
        assert len(errors) >= 2
        error_types = {type(e).__name__ for e in errors}
        assert "ResolutionError" in error_types or "CircularDependencyError" in error_types
        assert "ScopeMismatchError" in error_types or "CircularDependencyError" in error_types


class TestOptionalDeps:
    """Optional dependencies don't fail validation."""

    def test_optional_dep_with_default_ok(self) -> None:
        """Params with defaults are OK even if dependency not registered."""
        container = Container()
        container.register(ServiceWithOptionalDep)
        container.validate()  # Should not raise


class TestAutoWirableConcrete:
    """Auto-wirable concrete deps don't fail validation."""

    def test_unregistered_concrete_class_ok(self) -> None:
        """Unregistered concrete classes are auto-wirable and don't fail."""
        container = Container()
        container.register(ServiceWithConcreteDep)
        container.validate()  # Should not raise
