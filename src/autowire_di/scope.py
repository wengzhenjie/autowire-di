"""Scope management: Singleton cache with thread-safe double-checked locking,
and ScopedCache for request-level lifecycle."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, AsyncGenerator, Callable, Generator, TYPE_CHECKING

from autowire_di.types import BindingKey

if TYPE_CHECKING:
    from autowire_di.providers import Provider
    from autowire_di.types import ResolverProtocol


class SingletonCache:
    """Thread-safe singleton instance cache with async support."""

    __slots__ = ("_instances", "_lock", "_async_lock")

    def __init__(self) -> None:
        self._instances: dict[BindingKey, Any] = {}
        self._lock = threading.RLock()
        self._async_lock: asyncio.Lock | None = None

    def _get_async_lock(self) -> asyncio.Lock:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def get_or_create(self, key: BindingKey, factory: Callable[[], Any]) -> Any:
        if key in self._instances:
            return self._instances[key]
        with self._lock:
            if key not in self._instances:
                self._instances[key] = factory()
            return self._instances[key]

    async def async_get_or_create(
        self,
        key: BindingKey,
        provider: Provider,
        resolver: ResolverProtocol,
        apply_interceptors: Callable[[Any], Any],
    ) -> Any:
        """Async-safe singleton creation with asyncio.Lock."""
        if key in self._instances:
            return self._instances[key]
        async with self._get_async_lock():
            if key in self._instances:
                return self._instances[key]
            from autowire_di.providers import FactoryProvider
            if isinstance(provider, FactoryProvider) and provider.is_async():
                value = await provider.async_provide(resolver)
            else:
                value = provider.provide(resolver)
            value = apply_interceptors(value)
            self._instances[key] = value
            return value

    def has(self, key: BindingKey) -> bool:
        return key in self._instances

    def set(self, key: BindingKey, value: Any) -> None:
        with self._lock:
            self._instances[key] = value

    def clear(self) -> None:
        with self._lock:
            self._instances.clear()


class ScopedCache:
    """Instance cache for a single scope lifetime.  Tracks teardown callbacks
    for resource cleanup when the scope exits."""

    __slots__ = ("_instances", "_teardowns", "_async_teardowns")

    def __init__(self) -> None:
        self._instances: dict[BindingKey, Any] = {}
        self._teardowns: list[Generator[Any, None, None]] = []
        self._async_teardowns: list[AsyncGenerator[Any, None]] = []

    def get(self, key: BindingKey) -> Any | None:
        return self._instances.get(key)

    def has(self, key: BindingKey) -> bool:
        return key in self._instances

    def set(self, key: BindingKey, value: Any) -> None:
        self._instances[key] = value

    def add_teardown(self, gen: Generator[Any, None, None]) -> None:
        self._teardowns.append(gen)

    def add_async_teardown(self, agen: AsyncGenerator[Any, None]) -> None:
        self._async_teardowns.append(agen)

    def dispose(self) -> None:
        errors: list[Exception] = []
        for gen in reversed(self._teardowns):
            try:
                next(gen, None)
            except StopIteration:
                pass
            except Exception as exc:
                errors.append(exc)
        self._teardowns.clear()
        self._instances.clear()
        if errors:
            raise ExceptionGroup("Errors during scope teardown", errors)

    async def async_dispose(self) -> None:
        errors: list[Exception] = []
        for agen in reversed(self._async_teardowns):
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass
            except Exception as exc:
                errors.append(exc)
        self._async_teardowns.clear()
        for gen in reversed(self._teardowns):
            try:
                next(gen, None)
            except StopIteration:
                pass
            except Exception as exc:
                errors.append(exc)
        self._teardowns.clear()
        self._instances.clear()
        if errors:
            raise ExceptionGroup("Errors during async scope teardown", errors)
