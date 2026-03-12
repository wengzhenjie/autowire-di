"""Module system for organizing related bindings into reusable groups."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autowire_di.container import Container


class Module(ABC):
    """Base class for grouping related bindings.

    Subclass and implement :meth:`configure` to register bindings::

        class InfraModule(Module):
            def configure(self, container: Container) -> None:
                container.register(DatabasePool, PostgresPool, scope=Scope.SINGLETON)
                container.register(Cache, RedisCache, scope=Scope.SINGLETON)

        container = Container()
        container.install(InfraModule())
    """

    @abstractmethod
    def configure(self, container: Container) -> None:
        """Register bindings on *container*."""


class PrivateModule(ABC):
    """A module whose bindings are private by default.

    Only bindings explicitly passed to :meth:`expose` are visible to the
    parent container.  This provides encapsulation for internal
    implementation details::

        class InternalModule(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(InternalHelper, InternalHelperImpl)
                container.register(PublicService, PublicServiceImpl)
                self.expose(PublicService)

    When installed, only ``PublicService`` is resolvable from the parent.
    """

    def __init__(self) -> None:
        self._exposed: list[tuple[type, str | None]] = []

    def expose(self, interface: type, *, name: str | None = None) -> None:
        """Mark *interface* (optionally with *name*) as visible to the parent."""
        self._exposed.append((interface, name))

    @abstractmethod
    def configure(self, container: Container) -> None:
        """Register bindings on a private child container.

        Call :meth:`expose` for each binding that should be visible to the
        parent container.
        """
