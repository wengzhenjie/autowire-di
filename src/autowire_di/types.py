from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Generator


class Scope(Enum):
    TRANSIENT = "transient"
    SINGLETON = "singleton"
    SCOPED = "scoped"


class ResolverProtocol(ABC):
    """Minimal interface that Provider implementations depend on.

    Defined here (in types) to break the circular import between
    providers.py and resolver.py / container.py.
    """

    @abstractmethod
    def resolve(self, interface: type, *, name: str | None = None, _chain: tuple[type, ...] = ()) -> Any: ...

    @abstractmethod
    def resolve_multi(self, interface: type) -> list[Any]: ...

    @abstractmethod
    def resolve_map(self, interface: type) -> dict[str, Any]: ...

    @abstractmethod
    def create_instance(self, cls: type, *, chain: tuple[type, ...] = ()) -> Any: ...

    @abstractmethod
    def resolve_callable_args(
        self,
        fn: Callable[..., Any],
        *,
        chain: tuple[type, ...] = (),
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def register_teardown(self, gen: Generator[Any, None, None]) -> None: ...

    @abstractmethod
    def register_async_teardown(self, agen: Any) -> None: ...


@dataclass(slots=True)
class Binding:
    interface: type
    provider: Any
    scope: Scope = Scope.TRANSIENT
    name: str | None = None
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
