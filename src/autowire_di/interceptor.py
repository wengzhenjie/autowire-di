"""AOP method interception — inspired by Guice's ``bindInterceptor``.

Allows cross-cutting concerns (logging, transactions, caching, auth) to be
applied declaratively without modifying business logic.

Usage::

    class LogInterceptor(MethodInterceptor):
        def invoke(self, invocation: MethodInvocation) -> Any:
            print(f"calling {invocation.method.__name__}")
            return invocation.proceed()

    container.bind_interceptor(
        class_matcher=annotated_with(Transactional),
        method_matcher=any_method(),
        interceptor=LogInterceptor(),
    )

    # Or use plain callables as matchers:
    container.bind_interceptor(
        class_matcher=lambda cls: hasattr(cls, "__aop_markers__"),
        method_matcher=lambda m: not m.__name__.startswith("_"),
        interceptor=LogInterceptor(),
    )
"""

from __future__ import annotations

import fnmatch
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# MethodInvocation — passed to interceptors
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MethodInvocation:
    """Represents a method call that can be intercepted."""

    instance: Any
    method: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    _interceptors: list[MethodInterceptor] = field(repr=False)
    _index: int = field(default=0, repr=False)

    def proceed(self) -> Any:
        """Invoke the next interceptor in the chain, or the real method."""
        if self._index < len(self._interceptors):
            interceptor = self._interceptors[self._index]
            self._index += 1
            return interceptor.invoke(self)
        return self.method(*self.args, **self.kwargs)


# ---------------------------------------------------------------------------
# MethodInterceptor — user implements this
# ---------------------------------------------------------------------------


class MethodInterceptor(ABC):
    """Base class for method interceptors.  Override :meth:`invoke`."""

    @abstractmethod
    def invoke(self, invocation: MethodInvocation) -> Any:
        """Handle the method invocation.  Call ``invocation.proceed()`` to
        continue the chain or invoke the real method."""


# ---------------------------------------------------------------------------
# Matcher — supports both ABC subclasses and plain callables
# ---------------------------------------------------------------------------


class Matcher(ABC):
    """Predicate for selecting classes or methods.

    Can also be used with plain ``Callable[[Any], bool]`` via the
    ``_CallableMatcher`` adapter — see :func:`_coerce_matcher`.
    """

    @abstractmethod
    def matches(self, target: Any) -> bool: ...

    def __and__(self, other: Matcher | Callable[[Any], bool]) -> Matcher:
        return _CompositeMatcher(lambda t, a=self, b=_coerce_matcher(other): a.matches(t) and b.matches(t))

    def __or__(self, other: Matcher | Callable[[Any], bool]) -> Matcher:
        return _CompositeMatcher(lambda t, a=self, b=_coerce_matcher(other): a.matches(t) or b.matches(t))

    def __invert__(self) -> Matcher:
        return _CompositeMatcher(lambda t, inner=self: not inner.matches(t))


class _CompositeMatcher(Matcher):
    """Matcher built from a predicate function — used for &, |, ~ composition."""
    __slots__ = ("_fn",)

    def __init__(self, fn: Callable[[Any], bool]) -> None:
        self._fn = fn

    def matches(self, target: Any) -> bool:
        return self._fn(target)


class _CallableMatcher(Matcher):
    """Adapter: wraps a plain ``Callable[[Any], bool]`` as a Matcher."""
    __slots__ = ("_fn",)

    def __init__(self, fn: Callable[[Any], bool]) -> None:
        self._fn = fn

    def matches(self, target: Any) -> bool:
        return self._fn(target)

    def __repr__(self) -> str:
        return f"CallableMatcher({self._fn!r})"


def _coerce_matcher(m: Matcher | Callable[[Any], bool]) -> Matcher:
    """Accept either a Matcher instance or a plain callable."""
    if isinstance(m, Matcher):
        return m
    return _CallableMatcher(m)


# ---------------------------------------------------------------------------
# Built-in matcher factories
# ---------------------------------------------------------------------------


def any_method() -> Matcher:
    """Match any method."""
    return _CompositeMatcher(lambda _: True)


def any_class() -> Matcher:
    """Match any class."""
    return _CompositeMatcher(lambda _: True)


def annotated_with(annotation: type) -> Matcher:
    """Match classes/methods decorated with ``@annotation`` (via ``__aop_markers__``)."""
    return _CompositeMatcher(
        lambda target, a=annotation: a in getattr(target, "__aop_markers__", set())
    )


def subclass_of(parent: type) -> Matcher:
    """Match classes that are subclasses of *parent*."""
    return _CompositeMatcher(
        lambda target, p=parent: isinstance(target, type) and issubclass(target, p)
    )


def name_matches(pattern: str) -> Matcher:
    """Match by name using fnmatch glob pattern."""
    return _CompositeMatcher(
        lambda target, pat=pattern: fnmatch.fnmatch(
            target.__name__ if hasattr(target, "__name__") else str(target), pat
        )
    )


# ---------------------------------------------------------------------------
# InterceptorBinding — stored in the container
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InterceptorBinding:
    class_matcher: Matcher
    method_matcher: Matcher
    interceptor: MethodInterceptor


# ---------------------------------------------------------------------------
# Proxy creation — wraps resolved instances
# ---------------------------------------------------------------------------


def _create_proxy(instance: Any, interceptor_bindings: list[InterceptorBinding]) -> Any:
    """Wrap *instance* methods with applicable interceptors.

    Creates a dynamic subclass proxy so that interception works correctly
    even for classes using ``__slots__`` or frozen dataclasses (where
    ``setattr`` on the instance would fail).
    """
    cls = type(instance)
    applicable = [b for b in interceptor_bindings if b.class_matcher.matches(cls)]
    if not applicable:
        return instance

    proxy_methods: dict[str, Any] = {}

    for name in _public_method_names(cls):
        method = getattr(cls, name, None)
        if method is None or not callable(method):
            continue

        method_interceptors = [
            b.interceptor for b in applicable if b.method_matcher.matches(method)
        ]
        if not method_interceptors:
            continue

        proxy_methods[name] = _make_intercepted_method(name, method_interceptors)

    if not proxy_methods:
        return instance

    proxy_cls = type(f"{cls.__name__}$Proxy", (cls,), {
        **proxy_methods,
        "__slots__": (),
        "__intercepted__": True,
    })
    proxy_cls.__qualname__ = f"{cls.__qualname__}$Proxy"
    proxy_cls.__module__ = cls.__module__

    proxy = object.__new__(proxy_cls)

    if hasattr(instance, "__dict__"):
        proxy.__dict__.update(instance.__dict__)

    for slot in _all_slots(cls):
        if slot.startswith("__") and slot.endswith("__"):
            continue
        try:
            val = getattr(instance, slot)
            object.__setattr__(proxy, slot, val)
        except AttributeError:
            pass

    return proxy


def _public_method_names(cls: type) -> list[str]:
    """Return names of public, non-dunder methods defined on *cls*."""
    result: list[str] = []
    for name in dir(cls):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name, None)
        if attr is not None and (callable(attr) or isinstance(attr, (classmethod, staticmethod))):
            result.append(name)
    return result


def _all_slots(cls: type) -> list[str]:
    """Collect all ``__slots__`` entries from *cls* and its bases."""
    slots: list[str] = []
    for klass in cls.__mro__:
        slots.extend(getattr(klass, "__slots__", ()))
    return slots


def _make_intercepted_method(
    method_name: str,
    interceptors: list[MethodInterceptor],
) -> Callable[..., Any]:
    """Build a replacement method that routes through the interceptor chain."""
    frozen_interceptors = list(interceptors)

    def intercepted(self: Any, *args: Any, **kwargs: Any) -> Any:
        original = getattr(type(self).__mro__[1], method_name)
        bound = original.__get__(self, type(self))
        invocation = MethodInvocation(
            instance=self,
            method=bound,
            args=args,
            kwargs=kwargs,
            _interceptors=list(frozen_interceptors),
        )
        return invocation.proceed()

    intercepted.__name__ = method_name
    intercepted.__qualname__ = method_name
    return intercepted


# ---------------------------------------------------------------------------
# Marker decorator — for annotated_with matching
# ---------------------------------------------------------------------------


def aop_mark(*markers: type) -> Callable[[Any], Any]:
    """Decorator to attach AOP markers to a class or method.

    Usage::

        class Transactional: pass

        @aop_mark(Transactional)
        class OrderService:
            ...

        # or on methods:
        class OrderService:
            @aop_mark(Transactional)
            def place_order(self): ...
    """
    def decorator(target: Any) -> Any:
        existing = getattr(target, "__aop_markers__", set())
        target.__aop_markers__ = existing | set(markers)
        return target
    return decorator
