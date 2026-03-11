"""Auto-wiring resolver: inspects ``__init__`` type hints to build dependency
graphs and create instances automatically."""

from __future__ import annotations

import inspect
from typing import Any, Callable, get_args, get_origin, get_type_hints

from autowire_di.markers import Inject, Named
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

            # --- Named(...) marker ---
            named_marker = _find_marker(metadata, Named)
            dep_name = named_marker.name if named_marker else None

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
    # Abstract hooks — implemented by Container / ScopedContainer
    # ------------------------------------------------------------------

    def resolve(self, interface: type, *, name: str | None = None, _chain: tuple[type, ...] = ()) -> Any:
        raise NotImplementedError

    def resolve_multi(self, interface: type) -> list[Any]:
        raise NotImplementedError

    def register_teardown(self, gen: Any) -> None:
        raise NotImplementedError

    def register_async_teardown(self, agen: Any) -> None:
        raise NotImplementedError

    def _get_config(self) -> dict[str, Any] | None:
        return None

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
