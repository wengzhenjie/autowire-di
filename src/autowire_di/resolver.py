"""Auto-wiring resolver: inspects ``__init__`` type hints to build dependency
graphs and create instances automatically."""

from __future__ import annotations

import inspect
import logging
import threading
import types as builtin_types
import typing
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, AsyncGenerator, Callable, Generator, get_args, get_origin, get_type_hints

from autowire_di.markers import Assisted, Inject, Named
from autowire_di.providers import ProviderWrapper
from autowire_di.types import CircularDependencyError, ResolverProtocol, ResolutionError

_logger = logging.getLogger("autowire_di")


def _is_abstract(cls: type) -> bool:
    """Return True if *cls* is an abstract class (ABC or Protocol) that should
    not be instantiated directly."""
    if inspect.isabstract(cls):
        return True
    if getattr(cls, "_is_protocol", False):
        return True
    return False


def _unwrap_annotated(hint: Any) -> tuple[type, list[Any]]:
    """If *hint* is ``Annotated[T, ...]`` return ``(T, [metadata...])``,
    otherwise ``(hint, [])``."""
    if get_origin(hint) is not None:
        args = get_args(hint)
        if get_origin(hint) is typing.Annotated:
            return args[0], list(args[1:])
    return hint, []


def _find_marker(metadata: list[Any], marker_type: type) -> Any | None:
    for m in metadata:
        if isinstance(m, marker_type):
            return m
    return None


# ---------------------------------------------------------------------------
# Parameter analysis cache — static introspection results cached per callable
# ---------------------------------------------------------------------------


class _ParamKind(Enum):
    CONFIG = auto()
    ASSISTED = auto()
    PROVIDER = auto()
    MULTI = auto()
    MAP = auto()
    DEPENDENCY = auto()


@dataclass(frozen=True, slots=True)
class _ParamSpec:
    """Pre-analysed parameter metadata (cacheable, no runtime state)."""
    name: str
    kind: _ParamKind
    base_type: type | None = None
    inner_type: type | None = None
    dep_name: str | None = None
    config_key: str | None = None
    has_default: bool = False
    is_optional: bool = False


_analysis_cache: dict[Callable[..., Any], list[_ParamSpec]] = {}
_analysis_lock = threading.Lock()


def _analyze_params(fn: Callable[..., Any]) -> list[_ParamSpec]:
    """Static analysis of a callable's parameters. Results are cached."""
    cached = _analysis_cache.get(fn)
    if cached is not None:
        return cached

    with _analysis_lock:
        cached = _analysis_cache.get(fn)
        if cached is not None:
            return cached

        try:
            hints = get_type_hints(fn, include_extras=True)
        except (NameError, AttributeError, TypeError) as exc:
            _logger.debug(
                "Cannot resolve type hints for %r (%s); treating as zero-argument callable",
                fn, exc,
            )
            _analysis_cache[fn] = []
            return []

        hints.pop("return", None)
        sig = inspect.signature(fn)
        specs: list[_ParamSpec] = []

        for name, param in sig.parameters.items():
            if name == "self":
                continue

            hint = hints.get(name)
            has_default = param.default is not inspect.Parameter.empty

            if hint is None:
                if has_default:
                    continue
                specs.append(_ParamSpec(
                    name=name, kind=_ParamKind.DEPENDENCY,
                    has_default=False, is_optional=False,
                ))
                continue

            base_type, metadata = _unwrap_annotated(hint)

            inject_marker = _find_marker(metadata, Inject)
            if inject_marker is not None:
                specs.append(_ParamSpec(
                    name=name, kind=_ParamKind.CONFIG,
                    config_key=inject_marker.config, has_default=has_default,
                ))
                continue

            if _find_marker(metadata, Assisted) is not None:
                specs.append(_ParamSpec(
                    name=name, kind=_ParamKind.ASSISTED, has_default=has_default,
                ))
                continue

            named_marker = _find_marker(metadata, Named)
            dep_name = named_marker.name if named_marker else None

            if _is_provider_type(base_type):
                inner = get_args(base_type)[0]
                specs.append(_ParamSpec(
                    name=name, kind=_ParamKind.PROVIDER,
                    inner_type=inner, dep_name=dep_name, has_default=has_default,
                ))
                continue

            origin = get_origin(base_type)
            if origin is list:
                inner_args = get_args(base_type)
                if inner_args:
                    specs.append(_ParamSpec(
                        name=name, kind=_ParamKind.MULTI,
                        inner_type=inner_args[0], dep_name=dep_name,
                        has_default=has_default, is_optional=_is_optional(hint),
                    ))
                    continue

            if origin is dict:
                inner_args = get_args(base_type)
                if len(inner_args) == 2 and inner_args[0] is str:
                    specs.append(_ParamSpec(
                        name=name, kind=_ParamKind.MAP,
                        inner_type=inner_args[1], dep_name=dep_name,
                        has_default=has_default, is_optional=_is_optional(hint),
                    ))
                    continue

            specs.append(_ParamSpec(
                name=name, kind=_ParamKind.DEPENDENCY,
                base_type=base_type, dep_name=dep_name,
                has_default=has_default, is_optional=_is_optional(hint),
            ))

        _analysis_cache[fn] = specs
        return specs


class Resolver(ResolverProtocol):
    """Resolves constructor parameters using type hints and a lookup callback."""

    def resolve_callable_args(
        self,
        fn: Callable[..., Any],
        *,
        chain: tuple[type, ...] = (),
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Inspect *fn*'s type hints and resolve each parameter.

        Returns a dict of ``{param_name: resolved_value}`` ready to be
        unpacked as ``fn(**kwargs)``.
        """
        specs = _analyze_params(fn)
        kwargs: dict[str, Any] = {}

        for spec in specs:
            if spec.kind == _ParamKind.CONFIG:
                assert spec.config_key is not None
                try:
                    kwargs[spec.name] = self._resolve_config(spec.config_key, config)
                except ResolutionError:
                    if spec.has_default:
                        continue
                    raise
                continue

            if spec.kind == _ParamKind.ASSISTED:
                continue

            if spec.kind == _ParamKind.PROVIDER:
                kwargs[spec.name] = ProviderWrapper(spec.inner_type, self, name=spec.dep_name)
                continue

            if spec.kind == _ParamKind.MULTI:
                try:
                    kwargs[spec.name] = self.resolve_multi(spec.inner_type)
                    continue
                except ResolutionError:
                    if spec.has_default or spec.is_optional:
                        pass
                    else:
                        raise

            if spec.kind == _ParamKind.MAP:
                try:
                    kwargs[spec.name] = self.resolve_map(spec.inner_type)
                    continue
                except ResolutionError:
                    if spec.has_default or spec.is_optional:
                        pass
                    else:
                        raise

            if spec.kind == _ParamKind.DEPENDENCY:
                if spec.base_type is None:
                    raise ResolutionError(
                        f"Parameter '{spec.name}' of {fn!r} has no type hint and no default value"
                    )
                try:
                    kwargs[spec.name] = self.resolve(spec.base_type, name=spec.dep_name, _chain=chain)
                except ResolutionError:
                    if spec.has_default:
                        continue
                    if spec.is_optional:
                        kwargs[spec.name] = None
                    else:
                        raise

        return kwargs

    def create_instance(self, cls: type, *, chain: tuple[type, ...] = ()) -> Any:
        """Auto-wire and instantiate *cls*."""
        if cls in chain:
            raise CircularDependencyError(chain, cls)
        if cls.__init__ is object.__init__:
            return cls()
        new_chain = (*chain, cls)
        kwargs = self.resolve_callable_args(
            cls.__init__,  # type: ignore[misc]
            chain=new_chain,
            config=self._get_config(),
        )
        return cls(**kwargs)

    def resolve_kwargs(self, cls: type) -> dict[str, Any]:
        """Resolve all constructor parameters of *cls* without instantiating it.

        Returns a ``dict[str, Any]`` suitable for passing as
        ``fn_constructor_kwargs`` to frameworks like Ray Data's
        ``map_batches``.
        """
        if cls.__init__ is object.__init__:
            return {}
        return self.resolve_callable_args(
            cls.__init__,  # type: ignore[misc]
            config=self._get_config(),
        )

    # ------------------------------------------------------------------
    # Assisted injection — factory generation
    # ------------------------------------------------------------------

    def create_factory(self, cls: type) -> Callable[..., Any]:
        """Return a factory function for *cls* that auto-wires injected
        parameters and accepts ``Assisted``-marked parameters as keyword
        arguments.

        Example::

            class Payment:
                def __init__(
                    self,
                    gateway: PaymentGateway,
                    amount: Annotated[float, Assisted()],
                    currency: Annotated[str, Assisted()],
                ): ...

            make_payment = container.create_factory(Payment)
            payment = make_payment(amount=100.0, currency="USD")
        """
        assisted_params = _get_assisted_params(cls)
        resolver = self

        def factory(**caller_kwargs: Any) -> Any:
            missing = set(assisted_params) - set(caller_kwargs)
            if missing:
                raise TypeError(
                    f"Missing assisted argument(s) for {cls.__name__}: "
                    f"{', '.join(sorted(missing))}"
                )
            injected = resolver.resolve_callable_args(
                cls.__init__,  # type: ignore[misc]
                config=resolver._get_config(),
            )
            injected.update(caller_kwargs)
            return cls(**injected)

        factory.__name__ = f"{cls.__name__}Factory"
        factory.__qualname__ = f"{cls.__qualname__}Factory"
        factory.__assisted_params__ = tuple(assisted_params)  # type: ignore[attr-defined]
        return factory

    # ------------------------------------------------------------------
    # Abstract hooks — implemented by Container / ScopedContainer
    # ------------------------------------------------------------------

    @abstractmethod
    def resolve(self, interface: type, *, name: str | None = None, _chain: tuple[type, ...] = ()) -> Any: ...

    @abstractmethod
    def resolve_multi(self, interface: type) -> list[Any]: ...

    @abstractmethod
    def resolve_map(self, interface: type) -> dict[str, Any]: ...

    @abstractmethod
    def register_teardown(self, gen: Generator[Any, None, None]) -> None: ...

    @abstractmethod
    def register_async_teardown(self, agen: AsyncGenerator[Any, None]) -> None: ...

    def _get_config(self) -> dict[str, Any] | None:
        return None

    def _get_root_resolver(self) -> Resolver:
        """Return the root container resolver for scope-safe ProviderWrapper binding."""
        return self

    # ------------------------------------------------------------------
    # Config resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_config(key: str, config: dict[str, Any] | None) -> Any:
        if config is None:
            raise ResolutionError(f"No configuration provided, cannot resolve config key '{key}'")
        parts = key.split(".")
        current: Any = config
        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    raise ResolutionError(f"Config key '{key}' not found (missing segment '{part}')")
                current = current[part]
            else:
                raise ResolutionError(
                    f"Config key '{key}': cannot traverse into non-dict value at '{part}'"
                )
        return current


def _get_assisted_params(cls: type) -> list[str]:
    """Return the names of parameters marked with ``Assisted()``."""
    specs = _analyze_params(cls.__init__)  # type: ignore[misc]
    return [s.name for s in specs if s.kind == _ParamKind.ASSISTED]


def _is_provider_type(hint: Any) -> bool:
    """Return True if *hint* is ``Provider[T]`` (our ProviderWrapper generic alias)."""
    origin = get_origin(hint)
    if origin is None:
        return False
    args = get_args(hint)
    if not args:
        return False
    return origin is ProviderWrapper


def _is_optional(hint: Any) -> bool:
    """Return True if *hint* is ``X | None`` or ``Optional[X]``."""
    origin = get_origin(hint)
    if origin is builtin_types.UnionType:
        return type(None) in get_args(hint)
    if origin is typing.Union:
        return type(None) in get_args(hint)
    return False
