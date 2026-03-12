from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Scope(Enum):
    TRANSIENT = "transient"
    SINGLETON = "singleton"
    SCOPED = "scoped"


@dataclass(slots=True)
class Binding:
    interface: type
    provider: Any  # Provider instance — typed loosely to avoid circular import
    scope: Scope = Scope.TRANSIENT
    name: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    eager: bool = False


BindingKey = tuple[type, str | None]


def make_key(interface: type, name: str | None = None) -> BindingKey:
    return (interface, name)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DIError(Exception):
    """Base exception for all DI errors."""


class ResolutionError(DIError):
    """Raised when a dependency cannot be resolved."""


class CircularDependencyError(DIError):
    """Raised when a circular dependency is detected."""

    def __init__(self, chain: tuple[type, ...], target: type) -> None:
        cycle = " -> ".join(t.__name__ for t in (*chain, target))
        super().__init__(f"Circular dependency detected: {cycle}")
        self.chain = chain
        self.target = target


class RegistrationError(DIError):
    """Raised when a binding registration is invalid."""


class ScopeMismatchError(DIError):
    """Raised when a longer-lived scope depends on a shorter-lived scope."""

    def __init__(self, consumer: type, consumer_scope: Scope, dependency: type, dep_scope: Scope):
        super().__init__(
            f"Scope mismatch: {consumer.__name__} ({consumer_scope.value}) "
            f"depends on {dependency.__name__} ({dep_scope.value}). "
            f"A {consumer_scope.value} service must not depend on a {dep_scope.value} service."
        )
        self.consumer = consumer
        self.consumer_scope = consumer_scope
        self.dependency = dependency
        self.dep_scope = dep_scope


class ValidationError(DIError):
    """Raised when container validation fails, wrapping one or more underlying errors."""

    def __init__(self, errors: list[DIError]) -> None:
        messages = [f"  - {e}" for e in errors]
        super().__init__(f"Container validation failed ({len(errors)} error(s)):\n" + "\n".join(messages))
        self.errors = errors


class ScopeNotActiveError(DIError):
    """Raised when resolving a scoped service outside of an active scope."""


# ---------------------------------------------------------------------------
# Scope ordering (for validation)
# ---------------------------------------------------------------------------

SCOPE_LIFETIME_ORDER: dict[Scope, int] = {
    Scope.TRANSIENT: 0,
    Scope.SCOPED: 1,
    Scope.SINGLETON: 2,
}
