"""Module system for organizing related bindings into reusable groups."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from python_di.container import Container


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
