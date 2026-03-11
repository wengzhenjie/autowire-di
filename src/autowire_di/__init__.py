"""py-di: A Pythonic dependency injection framework."""

from autowire_di.container import Container, ScopedContainer
from autowire_di.markers import Inject, Named
from autowire_di.module import Module
from autowire_di.providers import (
    AliasProvider,
    ClassProvider,
    FactoryProvider,
    Provider,
    ValueProvider,
)
from autowire_di.recipe import ContainerRecipe
from autowire_di.types import (
    Binding,
    CircularDependencyError,
    DIError,
    RegistrationError,
    ResolutionError,
    Scope,
    ScopeMismatchError,
    ScopeNotActiveError,
    ValidationError,
)

__all__ = [
    "Container",
    "ScopedContainer",
    "ContainerRecipe",
    "Module",
    "Scope",
    "Inject",
    "Named",
    "Binding",
    "Provider",
    "ClassProvider",
    "FactoryProvider",
    "ValueProvider",
    "AliasProvider",
    "DIError",
    "ResolutionError",
    "CircularDependencyError",
    "RegistrationError",
    "ScopeMismatchError",
    "ScopeNotActiveError",
    "ValidationError",
]
