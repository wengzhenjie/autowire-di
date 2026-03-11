"""Tests for resolve_kwargs, make_injectable, and ContainerRecipe — the DI
integration points for frameworks that manage object construction externally
(Ray Data, Spark, etc.)."""

from __future__ import annotations

import threading
from typing import Annotated, Protocol, runtime_checkable

import cloudpickle
import pytest

from autowire_di import Container, ContainerRecipe, Inject, Module, Named, Scope


# ---------------------------------------------------------------------------
# Fixture types
# ---------------------------------------------------------------------------


@runtime_checkable
class ModelRegistry(Protocol):
    def load(self, name: str) -> str: ...


class HuggingFaceRegistry:
    def load(self, name: str) -> str:
        return f"hf:{name}"


class Tokenizer:
    def __init__(self, vocab_size: int = 30000):
        self.vocab_size = vocab_size

    def tokenize(self, text: str) -> list[str]:
        return text.split()


class MetricsCollector:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1


class TorchPredictor:
    """Simulates a stateful callable class like those used with
    ``ray.data.Dataset.map_batches``."""

    def __init__(
        self,
        registry: ModelRegistry,
        tokenizer: Tokenizer,
        metrics: MetricsCollector,
        model_name: Annotated[str, Inject(config="model.name")],
        device: Annotated[str, Inject(config="model.device")],
    ):
        self.registry = registry
        self.tokenizer = tokenizer
        self.metrics = metrics
        self.model_name = model_name
        self.device = device

    def __call__(self, batch: dict[str, list[str]]) -> dict[str, list[str]]:
        self.metrics.record("predict")
        return {"output": [f"{self.device}:{t}" for t in batch.get("text", [])]}


class SimplePredictor:
    """A predictor with no dependencies — just a plain class."""

    def __call__(self, batch: dict[str, list[int]]) -> dict[str, list[int]]:
        return {"doubled": [x * 2 for x in batch.get("values", [])]}


class PredictorWithDefaults:
    def __init__(self, tokenizer: Tokenizer, batch_size: int = 32):
        self.tokenizer = tokenizer
        self.batch_size = batch_size

    def __call__(self, batch: dict) -> dict:
        return batch


class NamedDepsPredictor:
    def __init__(
        self,
        primary: Annotated[ModelRegistry, Named("primary")],
        fallback: Annotated[ModelRegistry, Named("fallback")],
    ):
        self.primary = primary
        self.fallback = fallback


class UnserializableResource:
    """A dependency that cannot survive standard pickle (holds a Lock)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def work(self) -> str:
        return "done"


class PredictorWithHeavyDep:
    def __init__(self, resource: UnserializableResource):
        self.resource = resource

    def __call__(self, batch: dict) -> dict:
        return {"status": self.resource.work()}


class InfraModule(Module):
    def configure(self, container: Container) -> None:
        container.register(ModelRegistry, HuggingFaceRegistry)
        container.register(Tokenizer)
        container.register(MetricsCollector)


# ---------------------------------------------------------------------------
# resolve_kwargs
# ---------------------------------------------------------------------------


class TestResolveKwargs:
    def _make_container(self) -> Container:
        c = Container(config={"model": {"name": "bert-base", "device": "cuda"}})
        c.register(ModelRegistry, HuggingFaceRegistry)
        c.register(Tokenizer)
        c.register(MetricsCollector)
        return c

    def test_returns_dict_with_all_params(self) -> None:
        c = self._make_container()
        kwargs = c.resolve_kwargs(TorchPredictor)

        assert isinstance(kwargs["registry"], HuggingFaceRegistry)
        assert isinstance(kwargs["tokenizer"], Tokenizer)
        assert isinstance(kwargs["metrics"], MetricsCollector)
        assert kwargs["model_name"] == "bert-base"
        assert kwargs["device"] == "cuda"

    def test_can_construct_manually(self) -> None:
        c = self._make_container()
        kwargs = c.resolve_kwargs(TorchPredictor)
        predictor = TorchPredictor(**kwargs)

        result = predictor({"text": ["hello", "world"]})
        assert result == {"output": ["cuda:hello", "cuda:world"]}

    def test_empty_init(self) -> None:
        c = Container()
        kwargs = c.resolve_kwargs(SimplePredictor)
        assert kwargs == {}

    def test_with_default_params(self) -> None:
        c = Container()
        c.register(Tokenizer)
        kwargs = c.resolve_kwargs(PredictorWithDefaults)

        assert isinstance(kwargs["tokenizer"], Tokenizer)
        assert "batch_size" in kwargs

    def test_named_bindings(self) -> None:
        c = Container()
        c.register(ModelRegistry, HuggingFaceRegistry, name="primary")
        c.register(ModelRegistry, HuggingFaceRegistry, name="fallback")

        kwargs = c.resolve_kwargs(NamedDepsPredictor)
        assert isinstance(kwargs["primary"], HuggingFaceRegistry)
        assert isinstance(kwargs["fallback"], HuggingFaceRegistry)

    def test_singleton_returns_same_instance(self) -> None:
        c = Container()
        c.register(ModelRegistry, HuggingFaceRegistry, scope=Scope.SINGLETON)
        c.register(Tokenizer)
        c.register(MetricsCollector)
        c.set_config({"model": {"name": "bert", "device": "cpu"}})

        kwargs1 = c.resolve_kwargs(TorchPredictor)
        kwargs2 = c.resolve_kwargs(TorchPredictor)
        assert kwargs1["registry"] is kwargs2["registry"]

    def test_simulates_ray_fn_constructor_kwargs(self) -> None:
        """Demonstrates the intended usage pattern with fn_constructor_kwargs."""
        c = self._make_container()
        fn_constructor_kwargs = c.resolve_kwargs(TorchPredictor)

        instance = TorchPredictor(**fn_constructor_kwargs)
        assert instance.model_name == "bert-base"
        assert isinstance(instance.registry, HuggingFaceRegistry)


# ---------------------------------------------------------------------------
# ContainerRecipe
# ---------------------------------------------------------------------------


class TestContainerRecipe:
    def test_recipe_from_register_calls(self) -> None:
        c = Container(config={"model": {"name": "bert", "device": "cpu"}})
        c.register(ModelRegistry, HuggingFaceRegistry)
        c.register(Tokenizer)

        recipe = c.recipe
        rebuilt = recipe.build()
        assert isinstance(rebuilt.resolve(ModelRegistry), HuggingFaceRegistry)
        assert isinstance(rebuilt.resolve(Tokenizer), Tokenizer)

    def test_recipe_from_module(self) -> None:
        c = Container(config={"model": {"name": "bert", "device": "cpu"}})
        c.install(InfraModule())

        rebuilt = c.recipe.build()
        assert isinstance(rebuilt.resolve(ModelRegistry), HuggingFaceRegistry)

    def test_recipe_with_override(self) -> None:
        c = Container()
        c.register(ModelRegistry, HuggingFaceRegistry, name="main")
        c.override(ModelRegistry, HuggingFaceRegistry, name="main", scope=Scope.SINGLETON)

        rebuilt = c.recipe.build()
        r1 = rebuilt.resolve(ModelRegistry, name="main")
        r2 = rebuilt.resolve(ModelRegistry, name="main")
        assert r1 is r2

    def test_recipe_with_register_multi(self) -> None:
        c = Container()
        c.register_multi(ModelRegistry, HuggingFaceRegistry)
        c.register_multi(ModelRegistry, HuggingFaceRegistry)

        rebuilt = c.recipe.build()
        assert len(rebuilt.resolve_multi(ModelRegistry)) == 2

    def test_recipe_with_set_config(self) -> None:
        c = Container()
        c.set_config({"key": "value"})

        rebuilt = c.recipe.build()
        assert rebuilt.config == {"key": "value"}

    def test_recipe_cloudpickle_roundtrip(self) -> None:
        c = Container(config={"model": {"name": "bert", "device": "cpu"}})
        c.register(ModelRegistry, HuggingFaceRegistry)
        c.register(Tokenizer)
        c.register(MetricsCollector)

        recipe = c.recipe
        restored: ContainerRecipe = cloudpickle.loads(cloudpickle.dumps(recipe))
        rebuilt = restored.build()

        assert isinstance(rebuilt.resolve(ModelRegistry), HuggingFaceRegistry)
        assert isinstance(rebuilt.resolve(Tokenizer), Tokenizer)
        assert rebuilt.config == {"model": {"name": "bert", "device": "cpu"}}

    def test_recipe_with_module_cloudpickle_roundtrip(self) -> None:
        c = Container(config={"model": {"name": "bert", "device": "cpu"}})
        c.install(InfraModule())

        restored: ContainerRecipe = cloudpickle.loads(cloudpickle.dumps(c.recipe))
        rebuilt = restored.build()
        assert isinstance(rebuilt.resolve(ModelRegistry), HuggingFaceRegistry)

    def test_recipe_does_not_duplicate_module_specs(self) -> None:
        """Module registrations should not appear as individual specs."""
        c = Container()
        c.install(InfraModule())
        c.register(Tokenizer, name="extra")

        recipe = c.recipe
        assert len(recipe.modules) == 1
        assert len(recipe.specs) == 1  # only the extra register(), not module internals


# ---------------------------------------------------------------------------
# make_injectable
# ---------------------------------------------------------------------------


class TestMakeInjectable:
    def _make_container(self) -> Container:
        c = Container(config={"model": {"name": "bert-base", "device": "cuda"}})
        c.register(ModelRegistry, HuggingFaceRegistry)
        c.register(Tokenizer)
        c.register(MetricsCollector)
        return c

    def test_zero_arg_construction(self) -> None:
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor)

        instance = Cls()
        assert isinstance(instance, TorchPredictor)
        assert isinstance(instance.registry, HuggingFaceRegistry)
        assert instance.model_name == "bert-base"
        assert instance.device == "cuda"

    def test_callable_behavior_preserved(self) -> None:
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor)

        instance = Cls()
        result = instance({"text": ["hello"]})
        assert result == {"output": ["cuda:hello"]}

    def test_is_subclass(self) -> None:
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor)

        assert issubclass(Cls, TorchPredictor)
        assert isinstance(Cls(), TorchPredictor)

    def test_overrides(self) -> None:
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor, device="cpu")

        instance = Cls()
        assert instance.device == "cpu"
        assert instance.model_name == "bert-base"

    def test_class_name(self) -> None:
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor)

        assert "TorchPredictor" in Cls.__name__
        assert "Injectable" in Cls.__name__

    def test_recipe_introspection(self) -> None:
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor)

        assert hasattr(Cls, "__injectable_recipe__")
        assert isinstance(Cls.__injectable_recipe__, ContainerRecipe)

    def test_empty_init(self) -> None:
        c = Container()
        Cls = c.make_injectable(SimplePredictor)

        instance = Cls()
        result = instance({"values": [1, 2, 3]})
        assert result == {"doubled": [2, 4, 6]}

    def test_multiple_injectable_classes_independent(self) -> None:
        c = Container(config={"model": {"name": "bert", "device": "cuda"}})
        c.register(ModelRegistry, HuggingFaceRegistry)
        c.register(Tokenizer)
        c.register(MetricsCollector)

        Cls1 = c.make_injectable(TorchPredictor, device="cuda:0")
        Cls2 = c.make_injectable(TorchPredictor, device="cuda:1")

        assert Cls1().device == "cuda:0"
        assert Cls2().device == "cuda:1"

    def test_simulates_ray_map_batches(self) -> None:
        """End-to-end simulation of the Ray Data map_batches pattern."""
        c = self._make_container()
        InjectablePredictor = c.make_injectable(TorchPredictor)

        assert isinstance(InjectablePredictor, type)
        worker_instance = InjectablePredictor()
        batch = {"text": ["foo", "bar"]}
        result = worker_instance(batch)
        assert result == {"output": ["cuda:foo", "cuda:bar"]}

    def test_with_module(self) -> None:
        c = Container(config={"model": {"name": "bert", "device": "cpu"}})
        c.install(InfraModule())

        Cls = c.make_injectable(TorchPredictor)
        instance = Cls()
        assert isinstance(instance.registry, HuggingFaceRegistry)
        assert instance.device == "cpu"


# ---------------------------------------------------------------------------
# Serialization (cloudpickle) — the core value proposition
# ---------------------------------------------------------------------------


class TestInjectableCloudpickle:
    def _make_container(self) -> Container:
        c = Container(config={"model": {"name": "bert-base", "device": "cuda"}})
        c.register(ModelRegistry, HuggingFaceRegistry)
        c.register(Tokenizer)
        c.register(MetricsCollector)
        return c

    def test_injectable_class_survives_cloudpickle(self) -> None:
        """The entire Injectable class must survive cloudpickle roundtrip —
        this is what Ray does when shipping the class to workers."""
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor)

        restored = cloudpickle.loads(cloudpickle.dumps(Cls))
        instance = restored()

        assert isinstance(instance, TorchPredictor)
        assert instance.model_name == "bert-base"
        assert instance.device == "cuda"
        assert isinstance(instance.registry, HuggingFaceRegistry)

    def test_injectable_with_overrides_survives_cloudpickle(self) -> None:
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor, device="cpu")

        restored = cloudpickle.loads(cloudpickle.dumps(Cls))
        instance = restored()
        assert instance.device == "cpu"
        assert instance.model_name == "bert-base"

    def test_injectable_callable_after_cloudpickle(self) -> None:
        c = self._make_container()
        Cls = c.make_injectable(TorchPredictor)

        restored = cloudpickle.loads(cloudpickle.dumps(Cls))
        instance = restored()
        result = instance({"text": ["hello", "world"]})
        assert result == {"output": ["cuda:hello", "cuda:world"]}

    def test_injectable_with_module_survives_cloudpickle(self) -> None:
        c = Container(config={"model": {"name": "gpt2", "device": "cpu"}})
        c.install(InfraModule())

        Cls = c.make_injectable(TorchPredictor)
        restored = cloudpickle.loads(cloudpickle.dumps(Cls))
        instance = restored()

        assert instance.model_name == "gpt2"
        assert isinstance(instance.registry, HuggingFaceRegistry)

    def test_unserializable_dep_works_with_lazy_injectable(self) -> None:
        """Dependencies with unpicklable state (e.g. threading.Lock) work
        fine because make_injectable uses lazy rebuild — the Lock is created
        fresh on the worker side, never serialized."""
        c = Container()
        c.register(UnserializableResource)

        Cls = c.make_injectable(PredictorWithHeavyDep)

        # cloudpickle the class (simulates Ray shipping it to a worker)
        restored = cloudpickle.loads(cloudpickle.dumps(Cls))
        instance = restored()
        assert instance({"x": 1}) == {"status": "done"}

    def test_resolve_kwargs_with_unserializable_dep_fails(self) -> None:
        """In contrast, resolve_kwargs eagerly creates the Lock-holding
        object — cloudpickling that dict will fail."""
        c = Container()
        c.register(UnserializableResource)

        kwargs = c.resolve_kwargs(PredictorWithHeavyDep)
        with pytest.raises(TypeError):
            cloudpickle.dumps(kwargs)

    def test_injectable_simple_predictor_cloudpickle(self) -> None:
        c = Container()
        Cls = c.make_injectable(SimplePredictor)

        restored = cloudpickle.loads(cloudpickle.dumps(Cls))
        result = restored()({"values": [10, 20]})
        assert result == {"doubled": [20, 40]}
