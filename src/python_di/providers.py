from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class Provider(Protocol):
    """Strategy for creating a dependency instance."""

    def provide(self, resolver: Any) -> Any:
        """Create and return an instance.  *resolver* is the active resolver
        (typically the Container or ScopedContainer) used to resolve nested
        dependencies."""
        ...

    def is_async(self) -> bool:
        """Return ``True`` if :meth:`provide` must be awaited."""
        ...


class ClassProvider:
    """Resolve a class by auto-wiring its ``__init__`` parameters."""

    __slots__ = ("cls",)

    def __init__(self, cls: type) -> None:
        self.cls = cls

    def provide(self, resolver: Any) -> Any:
        return resolver.create_instance(self.cls)

    def is_async(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"ClassProvider({self.cls.__name__})"


class ValueProvider:
    """Return a pre-existing instance (always the same object)."""

    __slots__ = ("_value",)

    def __init__(self, value: Any) -> None:
        self._value = value

    def provide(self, resolver: Any) -> Any:
        return self._value

    def is_async(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"ValueProvider({self._value!r})"


class FactoryProvider:
    """Invoke a callable to create an instance.

    Supports three callable styles:

    1. **Plain function** — called with auto-wired arguments.
    2. **Generator function** (``yield``) — the yielded value is the instance;
       code after ``yield`` runs on teardown (sync).
    3. **Async generator function** (``async yield``) — same as (2) but async.
    """

    __slots__ = ("_factory", "_is_gen", "_is_async_gen", "_is_coroutine")

    def __init__(self, factory: Callable[..., Any]) -> None:
        self._factory = factory
        self._is_gen = inspect.isgeneratorfunction(factory)
        self._is_async_gen = inspect.isasyncgenfunction(factory)
        self._is_coroutine = asyncio.iscoroutinefunction(factory) and not self._is_async_gen

    @property
    def factory(self) -> Callable[..., Any]:
        return self._factory

    @property
    def is_generator(self) -> bool:
        return self._is_gen

    @property
    def is_async_generator(self) -> bool:
        return self._is_async_gen

    def provide(self, resolver: Any) -> Any:
        kwargs = resolver.resolve_callable_args(self._factory)
        if self._is_gen:
            gen = self._factory(**kwargs)
            value = next(gen)
            resolver.register_teardown(gen)
            return value
        if self._is_async_gen or self._is_coroutine:
            raise RuntimeError(
                f"Async factory {self._factory!r} must be resolved via async_provide(). "
                "Use `await scope.resolve(...)` inside an async scope."
            )
        return self._factory(**kwargs)

    async def async_provide(self, resolver: Any) -> Any:
        kwargs = resolver.resolve_callable_args(self._factory)
        if self._is_async_gen:
            agen = self._factory(**kwargs)
            value = await agen.__anext__()
            resolver.register_async_teardown(agen)
            return value
        if self._is_coroutine:
            return await self._factory(**kwargs)
        if self._is_gen:
            gen = self._factory(**kwargs)
            value = next(gen)
            resolver.register_teardown(gen)
            return value
        return self._factory(**kwargs)

    def is_async(self) -> bool:
        return self._is_async_gen or self._is_coroutine

    def __repr__(self) -> str:
        return f"FactoryProvider({self._factory!r})"


class AliasProvider:
    """Resolve by delegating to another registered type."""

    __slots__ = ("_target", "_target_name")

    def __init__(self, target: type, name: str | None = None) -> None:
        self._target = target
        self._target_name = name

    @property
    def target(self) -> type:
        return self._target

    @property
    def target_name(self) -> str | None:
        return self._target_name

    def provide(self, resolver: Any) -> Any:
        return resolver.resolve(self._target, name=self._target_name)

    def is_async(self) -> bool:
        return False

    def __repr__(self) -> str:
        suffix = f", name={self._target_name!r}" if self._target_name else ""
        return f"AliasProvider({self._target.__name__}{suffix})"
