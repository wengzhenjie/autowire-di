"""Tests for PrivateModule encapsulation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from autowire_di import Container, Module, PrivateModule, Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@runtime_checkable
class IPublicService(Protocol):
    def work(self) -> str: ...


class PublicServiceImpl:
    def __init__(self, helper: InternalHelper) -> None:
        self.helper = helper

    def work(self) -> str:
        return f"public:{self.helper.assist()}"


class InternalHelper:
    def assist(self) -> str:
        return "helped"


class AnotherInternal:
    pass


# ---------------------------------------------------------------------------
# Basic PrivateModule
# ---------------------------------------------------------------------------


class TestPrivateModuleBasic:
    def test_exposed_binding_resolvable(self) -> None:
        class MyModule(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(InternalHelper)
                container.register(IPublicService, PublicServiceImpl)
                self.expose(IPublicService)

        c = Container()
        c.install(MyModule())

        svc = c.resolve(IPublicService)
        assert svc.work() == "public:helped"

    def test_internal_binding_not_promoted(self) -> None:
        """Internal bindings registered via PrivateModule are not added to
        the parent registry — only exposed ones are.  Concrete classes can
        still be auto-wired, so we verify the registry directly."""

        class MyModule(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(InternalHelper)
                container.register(IPublicService, PublicServiceImpl)
                self.expose(IPublicService)

        c = Container()
        c.install(MyModule())

        assert c.registry.has(IPublicService)
        assert not c.registry.has(InternalHelper)

    def test_multiple_exposed_bindings(self) -> None:
        class MyModule(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(InternalHelper)
                container.register(IPublicService, PublicServiceImpl)
                self.expose(IPublicService)
                self.expose(InternalHelper)

        c = Container()
        c.install(MyModule())

        assert c.resolve(IPublicService).work() == "public:helped"
        assert c.resolve(InternalHelper).assist() == "helped"


# ---------------------------------------------------------------------------
# PrivateModule with scopes
# ---------------------------------------------------------------------------


class TestPrivateModuleScopes:
    def test_exposed_singleton(self) -> None:
        class MyModule(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(InternalHelper, scope=Scope.SINGLETON)
                container.register(IPublicService, PublicServiceImpl, scope=Scope.SINGLETON)
                self.expose(IPublicService)

        c = Container()
        c.install(MyModule())

        s1 = c.resolve(IPublicService)
        s2 = c.resolve(IPublicService)
        assert s1 is s2


# ---------------------------------------------------------------------------
# PrivateModule with named bindings
# ---------------------------------------------------------------------------


class TestPrivateModuleNamed:
    def test_expose_named_binding(self) -> None:
        class MyModule(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(InternalHelper, name="special")
                self.expose(InternalHelper, name="special")

        c = Container()
        c.install(MyModule())

        helper = c.resolve(InternalHelper, name="special")
        assert helper.assist() == "helped"


# ---------------------------------------------------------------------------
# Multiple PrivateModules
# ---------------------------------------------------------------------------


class TestMultiplePrivateModules:
    def test_two_private_modules_dont_leak(self) -> None:
        class ModuleA(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(InternalHelper)
                container.register(IPublicService, PublicServiceImpl)
                self.expose(IPublicService)

        class ModuleB(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(AnotherInternal)
                self.expose(AnotherInternal)

        c = Container()
        c.install(ModuleA())
        c.install(ModuleB())

        assert c.resolve(IPublicService).work() == "public:helped"
        assert isinstance(c.resolve(AnotherInternal), AnotherInternal)
        assert not c.registry.has(InternalHelper)


# ---------------------------------------------------------------------------
# PrivateModule mixed with regular Module
# ---------------------------------------------------------------------------


class TestPrivateWithRegularModule:
    def test_mixed_modules(self) -> None:
        class RegularModule(Module):
            def configure(self, container: Container) -> None:
                container.register(InternalHelper)

        class PrivModule(PrivateModule):
            def configure(self, container: Container) -> None:
                container.register(IPublicService, PublicServiceImpl)
                self.expose(IPublicService)

        c = Container()
        c.install(RegularModule())
        c.install(PrivModule())

        assert isinstance(c.resolve(InternalHelper), InternalHelper)
        assert c.resolve(IPublicService).work() == "public:helped"


# ---------------------------------------------------------------------------
# PrivateModule expose non-existent binding (silent)
# ---------------------------------------------------------------------------


class TestPrivateModuleEdgeCases:
    def test_expose_nonexistent_not_promoted(self) -> None:
        """Exposing a type that was never registered in the private module
        simply results in it not being added to the parent registry."""

        class MyModule(PrivateModule):
            def configure(self, container: Container) -> None:
                self.expose(InternalHelper)

        c = Container()
        c.install(MyModule())

        assert not c.registry.has(InternalHelper)
