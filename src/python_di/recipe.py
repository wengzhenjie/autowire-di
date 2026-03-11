"""Serializable container recipe — captures the *registration instructions*
(not resolved instances) so that a Container can be faithfully rebuilt on a
remote worker (Ray, Spark, etc.) without serializing live objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

from python_di.types import Scope

if TYPE_CHECKING:
    from python_di.container import Container


class _UnsetType:
    """Pickle-stable sentinel — a singleton whose identity survives
    cloudpickle / pickle roundtrips (unlike a bare ``object()``)."""

    _instance: _UnsetType | None = None

    def __new__(cls) -> _UnsetType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __reduce__(self) -> tuple[type[_UnsetType], tuple[()]]:
        return (_UnsetType, ())

    def __repr__(self) -> str:
        return "<UNSET>"

    def __bool__(self) -> bool:
        return False


_UNSET = _UnsetType()


class _Op(Enum):
    REGISTER = "register"
    REGISTER_MULTI = "register_multi"
    OVERRIDE = "override"
    SET_CONFIG = "set_config"


@dataclass(frozen=True, slots=True)
class BindingSpec:
    """A serializable record of a single ``container.register()`` (or
    ``register_multi`` / ``override``) call.  Stores the *arguments*, not the
    resulting Provider, so it can be replayed on a fresh Container."""

    op: _Op
    interface: type | None = None
    implementation: type | None = None
    factory: Callable[..., Any] | None = None
    instance: Any = _UNSET
    scope: Scope = Scope.TRANSIENT
    name: str | None = None

    def apply(self, container: Container) -> None:
        """Replay this registration on *container*."""
        kw: dict[str, Any] = {}
        if self.implementation is not None:
            kw["implementation"] = self.implementation
        if self.factory is not None:
            kw["factory"] = self.factory
        if self.instance is not _UNSET:
            kw["instance"] = self.instance

        if self.op is _Op.REGISTER:
            container.register(
                self.interface,  # type: ignore[arg-type]
                kw.pop("implementation", None),
                scope=self.scope,
                name=self.name,
                **kw,
            )
        elif self.op is _Op.REGISTER_MULTI:
            container.register_multi(
                self.interface,  # type: ignore[arg-type]
                kw.pop("implementation", None),
                scope=self.scope,
                **kw,
            )
        elif self.op is _Op.OVERRIDE:
            container.override(
                self.interface,  # type: ignore[arg-type]
                kw.pop("implementation", None),
                scope=self.scope,
                name=self.name,
                **kw,
            )
        elif self.op is _Op.SET_CONFIG:
            container.set_config(self.instance)  # config dict stored in instance slot


@dataclass(slots=True)
class ContainerRecipe:
    """A lightweight, serializable snapshot of everything needed to rebuild a
    :class:`Container` on a remote process.

    Contains module instances (which are typically stateless and picklable),
    the config dict, and a replay log of individual ``register()`` calls.
    """

    modules: tuple[Any, ...] = ()
    config: dict[str, Any] | None = None
    specs: tuple[BindingSpec, ...] = ()

    def build(self) -> Container:
        """Reconstruct a fully-configured Container from this recipe."""
        from python_di.container import Container

        c = Container(config=self.config)
        for module in self.modules:
            c.install(module)
        for spec in self.specs:
            spec.apply(c)
        return c
