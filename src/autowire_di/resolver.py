"""Auto-wiring resolver: inspects ``__init__`` type hints to build dependency
graphs and create instances automatically."""

from __future__ import annotations

import inspect
from typing import Any, Callable, get_args, get_origin, get_type_hints

from autowire_di.markers import Assisted, Inject, Named
from autowire_di.providers import ProviderWrapper
from autowire_di.types import CircularDependencyError, ResolutionError


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
        # typing.Annotated has origin = typing.Annotated in 3.11+
        try:
            from typing import Annotated
            if get_origin(hint) is Annotated:
                return args[0], list(args[1:])
        except ImportError:
            pass
    return hint, []


def _find_marker(metadata: list[Any], marker_type: type) -> Any | None:
    for m in metadata:
        if isinstance(m, marker_type):
            return m
    return None


class Resolver:
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
        try:
            hints = get_type_hints(fn, include_extras=True)
        except Exception:
            return {}

        hints.pop("return", None)
        sig = inspect.signature(fn)
        kwargs: dict[str, Any] = {}

        for name, param in sig.parameters.items():
            if name == "self":
                continue

            hint = hints.get(name)
            if hint is None:
                if param.default is not inspect.Parameter.empty:
                    continue
                raise ResolutionError(
                    f"Parameter '{name}' of {fn!r} has no type hint and no default value"
                )

            base_type, metadata = _unwrap_annotated(hint)

            # --- Inject(config=...) marker ---
            inject_marker = _find_marker(metadata, Inject)
            if inject_marker is not None:
                kwargs[name] = self._resolve_config(inject_marker.config, config)
                continue

            # --- Assisted() marker — skip, caller provides this ---
            if _find_marker(metadata, Assisted) is not None:
                continue

            # --- Named(...) marker ---
            named_marker = _find_marker(metadata, Named)
            dep_name = named_marker.name if named_marker else None

            # --- Provider[T] lazy injection ---
            if _is_provider_type(base_type):
                inner = get_args(base_type)[0]
                kwargs[name] = ProviderWrapper(inner, self, name=dep_name)
                continue

            # --- list[T] multi-binding ---
            origin = get_origin(base_type)
            if origin is list:
                inner_args = get_args(base_type)
                if inner_args:
                    try:
                        kwargs[name] = self.resolve_multi(inner_args[0])
                        continue
                    except (ResolutionError, AttributeError):
                        pass

            # --- dict[str, T] map-binding ---
            if origin is dict:
                inner_args = get_args(base_type)
                if len(inner_args) == 2 and inner_args[0] is str:
                    try:
                        kwargs[name] = self.resolve_map(inner_args[1])
                        continue
                    except (ResolutionError, AttributeError):
                        pass

            # --- Normal resolution ---
            try:
                kwargs[name] = self.resolve(base_type, name=dep_name, _chain=chain)
            except ResolutionError:
                if param.default is not inspect.Parameter.empty:
                    kwargs[name] = param.default
                elif _is_optional(hint):
                    kwargs[name] = None
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

    def resolve(self, interface: type, *, name: str | None = None, _chain: tuple[type, ...] = ()) -> Any:
        raise NotImplementedError

    def resolve_multi(self, interface: type) -> list[Any]:
        raise NotImplementedError

    def resolve_map(self, interface: type) -> dict[str, Any]:
        raise NotImplementedError

    def register_teardown(self, gen: Any) -> None:
        raise NotImplementedError

    def register_async_teardown(self, agen: Any) -> None:
        raise NotImplementedError

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
    try:
        hints = get_type_hints(cls.__init__, include_extras=True)  # type: ignore[misc]
    except Exception:
        return []
    hints.pop("return", None)
    sig = inspect.signature(cls.__init__)  # type: ignore[misc]
    result: list[str] = []
    for name, _param in sig.parameters.items():
        if name == "self":
            continue
        hint = hints.get(name)
        if hint is None:
            continue
        _base, metadata = _unwrap_annotated(hint)
        if _find_marker(metadata, Assisted) is not None:
            result.append(name)
    return result


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
    import types as builtin_types

    origin = get_origin(hint)
    if origin is builtin_types.UnionType:
        return type(None) in get_args(hint)
    # typing.Union
    try:
        import typing
        if origin is typing.Union:
            return type(None) in get_args(hint)
    except AttributeError:
        pass
    return False
