"""Startup validation: statically analyse the dependency graph to detect
missing bindings, circular dependencies, and scope mismatches *before*
any instance is created."""

from __future__ import annotations

import inspect
from typing import get_origin, get_type_hints

from autowire_di.markers import Inject, Named
from autowire_di.providers import AliasProvider, ClassProvider, FactoryProvider
from autowire_di.resolver import _is_abstract, _unwrap_annotated, _find_marker
from autowire_di.types import (
    Binding,
    CircularDependencyError,
    DIError,
    ResolutionError,
    Scope,
    ScopeMismatchError,
    ValidationError,
    SCOPE_LIFETIME_ORDER,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autowire_di.container import Container


def validate_container(container: Container) -> None:
    """Validate all registered bindings.  Raises :class:`ValidationError` if
    any problems are found."""
    errors: list[DIError] = []
    visited: set[type] = set()

    for binding in container.registry.all_bindings():
        _validate_binding(container, binding, errors, visited, chain=())

    if errors:
        raise ValidationError(errors)


def _validate_binding(
    container: Container,
    binding: Binding,
    errors: list[DIError],
    visited: set[type],
    *,
    chain: tuple[type, ...],
) -> None:
    iface = binding.interface
    if iface in visited:
        return
    visited.add(iface)

    target_cls = _get_target_class(binding)
    if target_cls is None:
        return

    if target_cls in chain:
        errors.append(CircularDependencyError(chain, target_cls))
        return

    new_chain = (*chain, target_cls)
    deps = _get_dependencies(target_cls, container)

    for dep_type, dep_name, has_default in deps:
        dep_binding = _lookup_binding(container, dep_type, dep_name)

        if dep_binding is None:
            if has_default:
                continue
            if not _is_abstract(dep_type) and isinstance(dep_type, type):
                continue
            errors.append(
                ResolutionError(
                    f"Missing binding: {iface.__name__} depends on "
                    f"{dep_type.__name__}"
                    + (f" (name={dep_name!r})" if dep_name else "")
                )
            )
            continue

        _check_scope_mismatch(binding, dep_binding, errors)
        dep_target = _get_target_class(dep_binding)
        if dep_target is not None and dep_target in new_chain:
            errors.append(CircularDependencyError(new_chain, dep_target))
            continue
        _validate_binding(container, dep_binding, errors, visited, chain=new_chain)


def _get_target_class(binding: Binding) -> type | None:
    provider = binding.provider
    if isinstance(provider, ClassProvider):
        return provider.cls
    if isinstance(provider, AliasProvider):
        return None
    if isinstance(provider, FactoryProvider):
        return None
    return None


def _get_dependencies(
    cls: type, container: Container
) -> list[tuple[type, str | None, bool]]:
    """Return a list of ``(type, name_or_None, has_default)`` for each
    constructor parameter of *cls*."""
    try:
        hints = get_type_hints(cls.__init__, include_extras=True)  # type: ignore[misc]
    except Exception:
        return []

    hints.pop("return", None)
    sig = inspect.signature(cls.__init__)  # type: ignore[misc]
    result: list[tuple[type, str | None, bool]] = []

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        hint = hints.get(param_name)
        if hint is None:
            continue

        base_type, metadata = _unwrap_annotated(hint)

        inject_marker = _find_marker(metadata, Inject)
        if inject_marker is not None:
            continue

        named_marker = _find_marker(metadata, Named)
        dep_name = named_marker.name if named_marker else None

        origin = get_origin(base_type)
        if origin is list:
            continue

        has_default = param.default is not inspect.Parameter.empty
        result.append((base_type, dep_name, has_default))

    return result


def _lookup_binding(container: Container, interface: type, name: str | None) -> Binding | None:
    return container._lookup(interface, name)


def _check_scope_mismatch(
    consumer: Binding, dependency: Binding, errors: list[DIError]
) -> None:
    """A longer-lived service must not depend on a shorter-lived service.
    Singleton > Scoped > Transient."""
    consumer_order = SCOPE_LIFETIME_ORDER[consumer.scope]
    dep_order = SCOPE_LIFETIME_ORDER[dependency.scope]
    if consumer_order > dep_order and dependency.scope != Scope.TRANSIENT:
        errors.append(
            ScopeMismatchError(
                consumer.interface,
                consumer.scope,
                dependency.interface,
                dependency.scope,
            )
        )
