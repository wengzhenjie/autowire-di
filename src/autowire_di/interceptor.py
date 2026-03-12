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
"""

from __future__ import annotations

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
# Matchers
# ---------------------------------------------------------------------------


class Matcher(ABC):
    """Predicate for selecting classes or methods."""

    @abstractmethod
    def matches(self, target: Any) -> bool: ...

    def __and__(self, other: Matcher) -> Matcher:
        return _AndMatcher(self, other)

    def __or__(self, other: Matcher) -> Matcher:
        return _OrMatcher(self, other)

    def __invert__(self) -> Matcher:
        return _NotMatcher(self)


class _AnyMatcher(Matcher):
    def matches(self, target: Any) -> bool:
        return True

    def __repr__(self) -> str:
        return "any()"


class _AnnotatedWithMatcher(Matcher):
    __slots__ = ("_annotation",)

    def __init__(self, annotation: type) -> None:
        self._annotation = annotation

    def matches(self, target: Any) -> bool:
        return self._annotation in getattr(target, "__aop_markers__", set())

    def __repr__(self) -> str:
        return f"annotated_with({self._annotation.__name__})"


class _SubclassOfMatcher(Matcher):
    __slots__ = ("_parent",)

    def __init__(self, parent: type) -> None:
        self._parent = parent

    def matches(self, target: Any) -> bool:
        return isinstance(target, type) and issubclass(target, self._parent)

    def __repr__(self) -> str:
        return f"subclass_of({self._parent.__name__})"


class _NameMatchesMatcher(Matcher):
    __slots__ = ("_pattern",)

    def __init__(self, pattern: str) -> None:
        self._pattern = pattern

    def matches(self, target: Any) -> bool:
        import fnmatch
        name = target.__name__ if hasattr(target, "__name__") else str(target)
        return fnmatch.fnmatch(name, self._pattern)

    def __repr__(self) -> str:
        return f"name_matches({self._pattern!r})"


class _AndMatcher(Matcher):
    __slots__ = ("_a", "_b")

    def __init__(self, a: Matcher, b: Matcher) -> None:
        self._a = a
        self._b = b

    def matches(self, target: Any) -> bool:
        return self._a.matches(target) and self._b.matches(target)


class _OrMatcher(Matcher):
    __slots__ = ("_a", "_b")

    def __init__(self, a: Matcher, b: Matcher) -> None:
        self._a = a
        self._b = b

    def matches(self, target: Any) -> bool:
        return self._a.matches(target) or self._b.matches(target)


class _NotMatcher(Matcher):
    __slots__ = ("_inner",)

    def __init__(self, inner: Matcher) -> None:
        self._inner = inner

    def matches(self, target: Any) -> bool:
        return not self._inner.matches(target)


# ---------------------------------------------------------------------------
# Public matcher factories
# ---------------------------------------------------------------------------


def any_method() -> Matcher:
    """Match any method."""
    return _AnyMatcher()


def any_class() -> Matcher:
    """Match any class."""
    return _AnyMatcher()


def annotated_with(annotation: type) -> Matcher:
    """Match classes/methods decorated with ``@annotation`` (via ``__aop_markers__``)."""
    return _AnnotatedWithMatcher(annotation)


def subclass_of(parent: type) -> Matcher:
    """Match classes that are subclasses of *parent*."""
    return _SubclassOfMatcher(parent)


def name_matches(pattern: str) -> Matcher:
    """Match by name using fnmatch glob pattern."""
    return _NameMatchesMatcher(pattern)


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
