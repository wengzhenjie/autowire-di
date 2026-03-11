"""python-di: A Pythonic dependency injection framework."""

from python_di.container import Container, ScopedContainer
from python_di.markers import Inject, Named
from python_di.module import Module
from python_di.providers import (
    AliasProvider,
    ClassProvider,
    FactoryProvider,
    Provider,
    ValueProvider,
)
from python_di.recipe import ContainerRecipe
from python_di.types import (
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
