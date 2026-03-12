"""Container — the main user-facing API that ties together Registry, Resolver,
ScopeManager, and Validator."""

from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
from typing import Any, Callable, Generator, AsyncGenerator, TypeVar

from autowire_di.interceptor import InterceptorBinding, Matcher, MethodInterceptor, _create_proxy
from autowire_di.providers import (
    ClassProvider,
    FactoryProvider,
    Provider,
    ValueProvider,
)
from autowire_di.recipe import BindingSpec, ContainerRecipe, _Op, _UNSET
from autowire_di.registry import Registry
from autowire_di.resolver import Resolver, _is_abstract
from autowire_di.scope import ScopedCache, SingletonCache
from autowire_di.types import (
    Binding,
    ResolutionError,
    Scope,
    ScopeNotActiveError,
    make_key,
)

_T = TypeVar("_T")

_SENTINEL = object()


# ======================================================================
# Mixin: Registration
# ======================================================================


class _RegistrationMixin:
    """Registration methods: register, register_multi, register_map, override."""

    _registry: Registry
    _recipe_specs: list[BindingSpec]

    def register(
        self,
        interface: type,
        implementation: type | None = None,
        *,
        factory: Callable[..., Any] | None = None,
        instance: Any = _SENTINEL,
        scope: Scope = Scope.TRANSIENT,
        name: str | None = None,
        eager: bool = False,
    ) -> None:
        """Register a binding.

        Exactly one of *implementation*, *factory*, or *instance* must be
        provided.  If only *interface* is given and it is a concrete class,
        it is registered as its own implementation.

        If *eager* is ``True`` and *scope* is ``SINGLETON``, the instance
        will be created immediately when :meth:`initialize_singletons` is
        called.
        """
        provider = _build_provider(interface, implementation, factory, instance)
        binding = Binding(interface=interface, provider=provider, scope=scope, name=name, eager=eager)
        self._registry.add(binding)
        self._recipe_specs.append(BindingSpec(
            op=_Op.REGISTER, interface=interface, implementation=implementation,
            factory=factory, instance=instance if instance is not _SENTINEL else _UNSET,
            scope=scope, name=name, eager=eager,
        ))

    def register_multi(
        self,
        interface: type,
        implementation: type | None = None,
        *,
        factory: Callable[..., Any] | None = None,
        instance: Any = _SENTINEL,
        scope: Scope = Scope.TRANSIENT,
    ) -> None:
        """Add a multi-binding (one of potentially many implementations for *interface*)."""
        provider = _build_provider(interface, implementation, factory, instance)
        binding = Binding(interface=interface, provider=provider, scope=scope)
        self._registry.add_multi(binding)
        self._recipe_specs.append(BindingSpec(
            op=_Op.REGISTER_MULTI, interface=interface, implementation=implementation,
            factory=factory, instance=instance if instance is not _SENTINEL else _UNSET,
            scope=scope,
        ))

    def register_map(
        self,
        interface: type,
        key: str,
        implementation: type | None = None,
        *,
        factory: Callable[..., Any] | None = None,
        instance: Any = _SENTINEL,
        scope: Scope = Scope.TRANSIENT,
    ) -> None:
        """Add a map-binding: associates *key* with a provider for *interface*.

        Resolve all entries via ``resolve_map(interface)`` which returns
        ``dict[str, T]``.
        """
        provider = _build_provider(interface, implementation, factory, instance)
        binding = Binding(interface=interface, provider=provider, scope=scope)
        self._registry.add_map(interface, key, binding)
        self._recipe_specs.append(BindingSpec(
            op=_Op.REGISTER_MAP, interface=interface, implementation=implementation,
            factory=factory, instance=instance if instance is not _SENTINEL else _UNSET,
            scope=scope, name=key,
        ))

    def override(
        self,
        interface: type,
        implementation: type | None = None,
        *,
        factory: Callable[..., Any] | None = None,
        instance: Any = _SENTINEL,
        scope: Scope | None = None,
        name: str | None = None,
    ) -> None:
        """Override an existing binding (or create one if it doesn't exist)."""
        existing = self._registry.get(interface, name)
        effective_scope = scope if scope is not None else (existing.scope if existing else Scope.TRANSIENT)
        provider = _build_provider(interface, implementation, factory, instance)
        binding = Binding(interface=interface, provider=provider, scope=effective_scope, name=name)
        self._registry.add(binding, allow_override=True)
        self._recipe_specs.append(BindingSpec(
            op=_Op.OVERRIDE, interface=interface, implementation=implementation,
            factory=factory, instance=instance if instance is not _SENTINEL else _UNSET,
            scope=effective_scope, name=name,
        ))


# ======================================================================
# Mixin: Lifecycle (teardown, eager init, dispose)
# ======================================================================


class _LifecycleMixin:
    """Lifecycle management: teardown registration, eager init, dispose."""

    _registry: Registry
    _teardowns: list[Generator[Any, None, None]]
    _async_teardowns: list[Any]
    _singletons: SingletonCache

    def initialize_singletons(self) -> None:
        """Eagerly create all singleton instances marked with ``eager=True``."""
        for binding in self._registry.all_bindings():
            if binding.scope == Scope.SINGLETON and binding.eager:
                self.resolve(binding.interface, name=binding.name)  # type: ignore[attr-defined]

    async def async_initialize_singletons(self) -> None:
        """Async version of :meth:`initialize_singletons`."""
        for binding in self._registry.all_bindings():
            if binding.scope == Scope.SINGLETON and binding.eager:
                await self.async_resolve(binding.interface, name=binding.name)  # type: ignore[attr-defined]

    def register_teardown(self, gen: Generator[Any, None, None]) -> None:
        self._teardowns.append(gen)

    def register_async_teardown(self, agen: Any) -> None:
        self._async_teardowns.append(agen)

    def dispose(self) -> None:
        for gen in reversed(self._teardowns):
            try:
                next(gen, None)
            except StopIteration:
                pass
        self._teardowns.clear()
        self._singletons.clear()

    async def async_dispose(self) -> None:
        for agen in reversed(self._async_teardowns):
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass
        self._async_teardowns.clear()
        for gen in reversed(self._teardowns):
            try:
                next(gen, None)
            except StopIteration:
                pass
        self._teardowns.clear()
        self._singletons.clear()


# ======================================================================
# Mixin: Interception (AOP)
# ======================================================================


class _InterceptionMixin:
    """AOP method interception support."""

    _interceptor_bindings: list[InterceptorBinding]
    _parent: Container | None
    _recipe_specs: list[BindingSpec]

    def bind_interceptor(
        self,
        class_matcher: Matcher,
        method_matcher: Matcher,
        interceptor: MethodInterceptor,
    ) -> None:
        """Register a method interceptor.

        All instances resolved from this container whose class matches
        *class_matcher* will have methods matching *method_matcher* wrapped
        by *interceptor*.
        """
        self._interceptor_bindings.append(
            InterceptorBinding(class_matcher, method_matcher, interceptor)
        )
        self._recipe_specs.append(BindingSpec(
            op=_Op.BIND_INTERCEPTOR,
            interceptor_args=(class_matcher, method_matcher, interceptor),
        ))

    def _apply_interceptors(self, instance: Any) -> Any:
        """Apply all registered interceptors to *instance*."""
        bindings = self._all_interceptor_bindings()
        if not bindings:
            return instance
        return _create_proxy(instance, bindings)

    def _all_interceptor_bindings(self) -> list[InterceptorBinding]:
        if self._parent is not None:
            return self._parent._all_interceptor_bindings() + self._interceptor_bindings  # type: ignore[union-attr]
        return list(self._interceptor_bindings)


# ======================================================================
# Container
# ======================================================================


class Container(_RegistrationMixin, _LifecycleMixin, _InterceptionMixin, Resolver):
    """Dependency injection container with auto-wiring, scoped lifecycles,
    and async support.

    Usage::

        container = Container()
        container.register(OrderRepository, PostgresOrderRepository)
        container.register(DatabasePool, PostgresPool, scope=Scope.SINGLETON)
        service = container.resolve(OrderService)
    """

    def __init__(
        self,
        *,
        parent: Container | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._registry = Registry()
        self._singletons = SingletonCache()
        self._parent = parent
        self._config = config
        self._teardowns: list[Generator[Any, None, None]] = []
        self._async_teardowns: list[Any] = []
        self._interceptor_bindings: list[InterceptorBinding] = []
        self._recipe_modules: list[Any] = []
        self._recipe_specs: list[BindingSpec] = []

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def config(self) -> dict[str, Any] | None:
        if self._config is not None:
            return self._config
        if self._parent is not None:
            return self._parent.config
        return None

    def set_config(self, config: dict[str, Any]) -> None:
        self._config = config
        self._recipe_specs.append(BindingSpec(op=_Op.SET_CONFIG, instance=config))

    def _get_config(self) -> dict[str, Any] | None:
        return self.config

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, interface: type, *, name: str | None = None, _chain: tuple[type, ...] = ()) -> Any:
        binding = self._lookup(interface, name)
        if binding is None:
            if not _is_abstract(interface) and isinstance(interface, type):
                return self.create_instance(interface, chain=_chain)
            raise ResolutionError(
                f"No binding registered for {interface.__name__}"
                + (f" (name={name!r})" if name else "")
            )
        return self._provide(binding, chain=_chain)

    def resolve_multi(self, interface: type) -> list[Any]:
        bindings = self._get_multi_bindings(interface)
        if not bindings:
            raise ResolutionError(f"No multi-bindings registered for {interface.__name__}")
        return [self._provide(b) for b in bindings]

    def resolve_map(self, interface: type) -> dict[str, Any]:
        """Resolve all map-bindings for *interface*, returning ``dict[str, T]``."""
        bindings = self._get_map_bindings(interface)
        if not bindings:
            raise ResolutionError(f"No map-bindings registered for {interface.__name__}")
        return {k: self._provide(b) for k, b in bindings.items()}

    async def async_resolve(
        self, interface: type, *, name: str | None = None, _chain: tuple[type, ...] = ()
    ) -> Any:
        binding = self._lookup(interface, name)
        if binding is None:
            if not _is_abstract(interface) and isinstance(interface, type):
                return self.create_instance(interface, chain=_chain)
            raise ResolutionError(
                f"No binding registered for {interface.__name__}"
                + (f" (name={name!r})" if name else "")
            )
        return await self._async_provide(binding, chain=_chain)

    # ------------------------------------------------------------------
    # Scope management
    # ------------------------------------------------------------------

    @contextmanager
    def new_scope(self) -> Generator[ScopedContainer, None, None]:
        scope = ScopedContainer(self)
        try:
            yield scope
        finally:
            scope.dispose()

    @asynccontextmanager
    async def new_async_scope(self) -> AsyncGenerator[ScopedContainer, None]:
        scope = ScopedContainer(self)
        try:
            yield scope
        finally:
            await scope.async_dispose()

    # ------------------------------------------------------------------
    # Child containers
    # ------------------------------------------------------------------

    def create_child(self, *, config: dict[str, Any] | None = None) -> Container:
        return Container(parent=self, config=config)

    # ------------------------------------------------------------------
    # Module installation
    # ------------------------------------------------------------------

    def install(self, module: Any) -> None:
        """Install a :class:`Module` or :class:`PrivateModule`.

        For a regular Module, calls ``module.configure(self)`` directly.
        For a PrivateModule, bindings are registered on an internal child
        container and only exposed bindings are promoted to this container.
        """
        from autowire_di.module import PrivateModule

        self._recipe_modules.append(module)
        snapshot = len(self._recipe_specs)

        if isinstance(module, PrivateModule):
            from autowire_di.providers import _ChildContainerProvider
            child = Container(parent=self, config=self._config)
            module.configure(child)
            for iface, exp_name in module._exposed:
                binding = child._registry.get(iface, exp_name)
                if binding is not None:
                    proxy_provider = _ChildContainerProvider(child, iface, exp_name)
                    exposed_binding = Binding(
                        interface=iface,
                        provider=proxy_provider,
                        scope=binding.scope,
                        name=exp_name,
                    )
                    self._registry.add(exposed_binding, allow_override=True)
        else:
            module.configure(self)

        del self._recipe_specs[snapshot:]

    # ------------------------------------------------------------------
    # Recipe (serializable container snapshot)
    # ------------------------------------------------------------------

    @property
    def recipe(self) -> ContainerRecipe:
        """Return a serializable recipe that can rebuild this container."""
        return ContainerRecipe(
            modules=tuple(self._recipe_modules),
            config=self._config,
            specs=tuple(self._recipe_specs),
        )

    # ------------------------------------------------------------------
    # Injectable class generation (for Ray Data, Spark UDFs, etc.)
    # ------------------------------------------------------------------

    def make_injectable(self, cls: type[_T], **overrides: Any) -> type[_T]:
        """Return a zero-argument subclass of *cls* whose ``__init__``
        lazily rebuilds the container from a serializable recipe and
        resolves all dependencies on the worker side.

        The closure captures only the recipe (a pure-data snapshot of
        registration instructions), *cls* (a regular class), and
        *overrides* (simple values) — all safely serializable via
        cloudpickle.  No live objects (model weights, connections, locks)
        are captured.
        """
        frozen_recipe = self.recipe
        frozen_overrides = dict(overrides)

        def __init__(self_: Any) -> None:
            container = frozen_recipe.build()
            kwargs = container.resolve_kwargs(cls)
            kwargs.update(frozen_overrides)
            cls.__init__(self_, **kwargs)

        injectable = type(
            f"{cls.__name__}__Injectable",
            (cls,),
            {"__init__": __init__, "__injectable_recipe__": frozen_recipe},
        )
        injectable.__qualname__ = f"{cls.__qualname__}__Injectable"
        injectable.__module__ = cls.__module__
        return injectable  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        from autowire_di.validator import validate_container
        validate_container(self)

    # ------------------------------------------------------------------
    # Introspection (used by Validator)
    # ------------------------------------------------------------------

    @property
    def registry(self) -> Registry:
        return self._registry

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _lookup(self, interface: type, name: str | None = None) -> Binding | None:
        binding = self._registry.get(interface, name)
        if binding is None and self._parent is not None:
            binding = self._parent._lookup(interface, name)
        return binding

    def _get_multi_bindings(self, interface: type) -> list[Binding]:
        bindings = self._registry.get_multi(interface)
        if self._parent is not None:
            bindings = self._parent._get_multi_bindings(interface) + bindings
        return bindings

    def _get_map_bindings(self, interface: type) -> dict[str, Binding]:
        parent_map: dict[str, Binding] = {}
        if self._parent is not None:
            parent_map = self._parent._get_map_bindings(interface)
        own = self._registry.get_map(interface)
        return {**parent_map, **own}

    def _provide(self, binding: Binding, *, chain: tuple[type, ...] = ()) -> Any:
        key = make_key(binding.interface, binding.name)
        if binding.scope == Scope.SINGLETON:
            return self._root_singletons.get_or_create(
                key, lambda: self._apply_interceptors(binding.provider.provide(self))
            )
        if binding.scope == Scope.SCOPED:
            raise ScopeNotActiveError(
                f"Cannot resolve scoped service {binding.interface.__name__} "
                f"outside of an active scope. Use container.new_scope()."
            )
        return self._apply_interceptors(binding.provider.provide(self))

    async def _async_provide(self, binding: Binding, *, chain: tuple[type, ...] = ()) -> Any:
        key = make_key(binding.interface, binding.name)
        if binding.scope == Scope.SINGLETON:
            if self._root_singletons.has(key):
                return self._root_singletons._instances[key]
            if isinstance(binding.provider, FactoryProvider) and binding.provider.is_async():
                value = await binding.provider.async_provide(self)
            else:
                value = binding.provider.provide(self)
            value = self._apply_interceptors(value)
            self._root_singletons.set(key, value)
            return value
        if binding.scope == Scope.SCOPED:
            raise ScopeNotActiveError(
                f"Cannot resolve scoped service {binding.interface.__name__} "
                f"outside of an active scope. Use container.new_async_scope()."
            )
        if isinstance(binding.provider, FactoryProvider) and binding.provider.is_async():
            return self._apply_interceptors(await binding.provider.async_provide(self))
        return self._apply_interceptors(binding.provider.provide(self))

    @property
    def _root_singletons(self) -> SingletonCache:
        if self._parent is not None:
            return self._parent._root_singletons
        return self._singletons


# ======================================================================
# ScopedContainer
# ======================================================================


class ScopedContainer(Resolver):
    """A scoped child of a :class:`Container`, created via
    ``container.new_scope()`` or ``container.new_async_scope()``.

    Scoped services are cached for the lifetime of this scope.  Singleton
    services are delegated to the root container.  Transient services are
    created fresh each time.
    """

    def __init__(self, root: Container) -> None:
        self._root = root
        self._cache = ScopedCache()

    def _get_config(self) -> dict[str, Any] | None:
        return self._root.config

    def _get_root_resolver(self) -> Container:
        return self._root

    def resolve(self, interface: type, *, name: str | None = None, _chain: tuple[type, ...] = ()) -> Any:
        binding = self._root._lookup(interface, name)
        if binding is None:
            if not _is_abstract(interface) and isinstance(interface, type):
                return self.create_instance(interface, chain=_chain)
            raise ResolutionError(
                f"No binding registered for {interface.__name__}"
                + (f" (name={name!r})" if name else "")
            )
        return self._provide(binding, chain=_chain)

    async def async_resolve(
        self, interface: type, *, name: str | None = None, _chain: tuple[type, ...] = ()
    ) -> Any:
        binding = self._root._lookup(interface, name)
        if binding is None:
            if not _is_abstract(interface) and isinstance(interface, type):
                return self.create_instance(interface, chain=_chain)
            raise ResolutionError(
                f"No binding registered for {interface.__name__}"
                + (f" (name={name!r})" if name else "")
            )
        return await self._async_provide(binding, chain=_chain)

    def resolve_multi(self, interface: type) -> list[Any]:
        bindings = self._root._get_multi_bindings(interface)
        if not bindings:
            raise ResolutionError(f"No multi-bindings registered for {interface.__name__}")
        return [self._provide(b) for b in bindings]

    def resolve_map(self, interface: type) -> dict[str, Any]:
        bindings = self._root._get_map_bindings(interface)
        if not bindings:
            raise ResolutionError(f"No map-bindings registered for {interface.__name__}")
        return {k: self._provide(b) for k, b in bindings.items()}

    def register_teardown(self, gen: Generator[Any, None, None]) -> None:
        self._cache.add_teardown(gen)

    def register_async_teardown(self, agen: Any) -> None:
        self._cache.add_async_teardown(agen)

    def dispose(self) -> None:
        self._cache.dispose()

    async def async_dispose(self) -> None:
        await self._cache.async_dispose()

    def _apply_interceptors(self, instance: Any) -> Any:
        return self._root._apply_interceptors(instance)

    def _provide(self, binding: Binding, *, chain: tuple[type, ...] = ()) -> Any:
        key = make_key(binding.interface, binding.name)

        if binding.scope == Scope.SINGLETON:
            return self._root._root_singletons.get_or_create(
                key, lambda: self._root._apply_interceptors(binding.provider.provide(self._root))
            )

        if binding.scope == Scope.SCOPED:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            value = self._apply_interceptors(binding.provider.provide(self))
            self._cache.set(key, value)
            return value

        return self._apply_interceptors(binding.provider.provide(self))

    async def _async_provide(self, binding: Binding, *, chain: tuple[type, ...] = ()) -> Any:
        key = make_key(binding.interface, binding.name)

        if binding.scope == Scope.SINGLETON:
            if self._root._root_singletons.has(key):
                return self._root._root_singletons._instances[key]
            if isinstance(binding.provider, FactoryProvider) and binding.provider.is_async():
                value = await binding.provider.async_provide(self._root)
            else:
                value = binding.provider.provide(self._root)
            value = self._root._apply_interceptors(value)
            self._root._root_singletons.set(key, value)
            return value

        if binding.scope == Scope.SCOPED:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            if isinstance(binding.provider, FactoryProvider) and binding.provider.is_async():
                value = await binding.provider.async_provide(self)
            else:
                value = binding.provider.provide(self)
            value = self._apply_interceptors(value)
            self._cache.set(key, value)
            return value

        if isinstance(binding.provider, FactoryProvider) and binding.provider.is_async():
            return self._apply_interceptors(await binding.provider.async_provide(self))
        return self._apply_interceptors(binding.provider.provide(self))


# ======================================================================
# Helpers
# ======================================================================


def _build_provider(
    interface: type,
    implementation: type | None,
    factory: Callable[..., Any] | None,
    instance: Any,
) -> Provider:
    given = sum([implementation is not None, factory is not None, instance is not _SENTINEL])
    if given > 1:
        raise ValueError(
            "Provide at most one of 'implementation', 'factory', or 'instance'."
        )
    if instance is not _SENTINEL:
        return ValueProvider(instance)
    if factory is not None:
        return FactoryProvider(factory)
    if implementation is not None:
        return ClassProvider(implementation)
    if isinstance(interface, type) and not _is_abstract(interface):
        return ClassProvider(interface)
    raise ValueError(
        f"Cannot register abstract type {interface.__name__} without an "
        f"implementation, factory, or instance."
    )
