"""Startup validation: statically analyse the dependency graph to detect
missing bindings, circular dependencies, and scope mismatches *before*
any instance is created."""

from __future__ import annotations

from typing import get_origin, TYPE_CHECKING

from autowire_di.providers import AliasProvider, ClassProvider, FactoryProvider
from autowire_di.resolver import (
    _ParamKind,
    _analyze_params,
    _is_abstract,
)
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

    provider = binding.provider

    if isinstance(provider, AliasProvider):
        target_binding = _lookup_binding(container, provider.target, provider.target_name)
        if target_binding is None:
            if not _is_abstract(provider.target) and isinstance(provider.target, type):
                return
            errors.append(
                ResolutionError(
                    f"AliasProvider: {iface.__name__} aliases "
                    f"{provider.target.__name__}"
                    + (f" (name={provider.target_name!r})" if provider.target_name else "")
                    + " which is not registered"
                )
            )
        else:
            _check_scope_mismatch(binding, target_binding, errors)
            _validate_binding(container, target_binding, errors, visited, chain=chain)
        return

    target_fn = _get_target_callable(binding)
    if target_fn is None:
        return

    target_cls = target_fn if isinstance(target_fn, type) else None
    if target_cls is not None and target_cls in chain:
        errors.append(CircularDependencyError(chain, target_cls))
        return

    new_chain = (*chain, target_cls) if target_cls is not None else chain
    deps = _get_dependencies_from_callable(target_fn)

    for dep_type, dep_name, has_default in deps:
        dep_binding = _lookup_binding(container, dep_type, dep_name)

        if dep_binding is None:
            if has_default:
                continue
            if not _is_abstract(dep_type) and isinstance(dep_type, type):
                continue
            label = iface.__name__
            errors.append(
                ResolutionError(
                    f"Missing binding: {label} depends on "
                    f"{dep_type.__name__}"
                    + (f" (name={dep_name!r})" if dep_name else "")
                )
            )
            continue

        _check_scope_mismatch(binding, dep_binding, errors)
        dep_target = _get_target_callable(dep_binding)
        dep_cls = dep_target if isinstance(dep_target, type) else None
        if dep_cls is not None and dep_cls in new_chain:
            errors.append(CircularDependencyError(new_chain, dep_cls))
            continue
        _validate_binding(container, dep_binding, errors, visited, chain=new_chain)


def _get_target_callable(binding: Binding) -> type | None:
    """Return the callable whose parameters should be validated."""
    provider = binding.provider
    if isinstance(provider, ClassProvider):
        return provider.cls
    if isinstance(provider, FactoryProvider):
        return provider.factory  # type: ignore[return-value]
    return None


def _get_dependencies_from_callable(
    fn: type | object,
) -> list[tuple[type, str | None, bool]]:
    """Extract dependency info from a callable using the cached param analysis."""
    target = fn.__init__ if isinstance(fn, type) else fn  # type: ignore[misc]
    specs = _analyze_params(target)
    result: list[tuple[type, str | None, bool]] = []

    for spec in specs:
        if spec.kind in (_ParamKind.CONFIG, _ParamKind.ASSISTED, _ParamKind.PROVIDER):
            continue
        if spec.kind == _ParamKind.MULTI:
            continue
        if spec.kind == _ParamKind.MAP:
            origin = get_origin(spec.inner_type) if spec.inner_type else None
            if origin is dict:
                continue
            continue
        if spec.kind == _ParamKind.DEPENDENCY and spec.base_type is not None:
            result.append((spec.base_type, spec.dep_name, spec.has_default or spec.is_optional))

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
