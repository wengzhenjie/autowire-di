from __future__ import annotations

from autowire_di.types import Binding, BindingKey, RegistrationError, make_key


class Registry:
    """Stores type -> Binding mappings with support for named and multi-bindings."""

    __slots__ = ("_bindings", "_multi_bindings")

    def __init__(self) -> None:
        self._bindings: dict[BindingKey, Binding] = {}
        self._multi_bindings: dict[type, list[Binding]] = {}

    # ------------------------------------------------------------------
    # Single bindings
    # ------------------------------------------------------------------

    def add(self, binding: Binding, *, allow_override: bool = False) -> None:
        key = make_key(binding.interface, binding.name)
        if key in self._bindings and not allow_override:
            existing = self._bindings[key]
            name_part = f" (name={binding.name!r})" if binding.name else ""
            raise RegistrationError(
                f"Binding for {binding.interface.__name__}{name_part} already registered "
                f"as {existing.provider}. Use allow_override=True or container.override() "
                f"to replace it."
            )
        self._bindings[key] = binding

    def get(self, interface: type, name: str | None = None) -> Binding | None:
        return self._bindings.get(make_key(interface, name))

    def has(self, interface: type, name: str | None = None) -> bool:
        return make_key(interface, name) in self._bindings

    def remove(self, interface: type, name: str | None = None) -> None:
        key = make_key(interface, name)
        self._bindings.pop(key, None)

    # ------------------------------------------------------------------
    # Multi-bindings  (list[T] resolution)
    # ------------------------------------------------------------------

    def add_multi(self, binding: Binding) -> None:
        self._multi_bindings.setdefault(binding.interface, []).append(binding)

    def get_multi(self, interface: type) -> list[Binding]:
        return list(self._multi_bindings.get(interface, []))

    def has_multi(self, interface: type) -> bool:
        return interface in self._multi_bindings

    # ------------------------------------------------------------------
    # Iteration / introspection
    # ------------------------------------------------------------------

    def all_bindings(self) -> list[Binding]:
        return list(self._bindings.values())

    def all_keys(self) -> list[BindingKey]:
        return list(self._bindings.keys())

    def __len__(self) -> int:
        return len(self._bindings)

    def __repr__(self) -> str:
        return f"Registry({len(self._bindings)} binding(s), {len(self._multi_bindings)} multi-binding(s))"
