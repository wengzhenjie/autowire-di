"""py-di: A Pythonic dependency injection framework."""

from autowire_di.container import Container, ScopedContainer
from autowire_di.interceptor import (
    Matcher,
    MethodInterceptor,
    MethodInvocation,
    annotated_with,
    any_class,
    any_method,
    aop_mark,
    name_matches,
    subclass_of,
)
from autowire_di.markers import Assisted, Inject, Named
from autowire_di.module import Module, PrivateModule
from autowire_di.providers import (
    AliasProvider,
    ClassProvider,
    FactoryProvider,
    Provider,
    ProviderWrapper,
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
    "PrivateModule",
    "Scope",
    "Assisted",
    "Inject",
    "Named",
    "Binding",
    "Provider",
    "ClassProvider",
    "FactoryProvider",
    "ValueProvider",
    "AliasProvider",
    "ProviderWrapper",
    "Matcher",
    "MethodInterceptor",
    "MethodInvocation",
    "annotated_with",
    "any_class",
    "any_method",
    "aop_mark",
    "name_matches",
    "subclass_of",
    "DIError",
    "ResolutionError",
    "CircularDependencyError",
    "RegistrationError",
    "ScopeMismatchError",
    "ScopeNotActiveError",
    "ValidationError",
]
