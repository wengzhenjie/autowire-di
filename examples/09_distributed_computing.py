"""分布式计算集成示例

演示 make_injectable、resolve_kwargs 和 ContainerRecipe 的用法。
这些特性专为 Ray Data、Spark UDF 等分布式场景设计。

注意：分布式序列化场景中避免使用 `from __future__ import annotations`，
因为它会将类型注解转为字符串，可能导致 cloudpickle 反序列化后类型解析失败。
"""

from typing import Annotated

import cloudpickle

from autowire_di import Container, Inject, Scope


# ── 模拟 ML 推理场景 ─────────────────────────────────────────────


class ModelRegistry:
    """模型注册表：管理模型加载。"""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        print(f"  [ModelRegistry] Loaded model: {model_name}")

    def predict(self, batch: list[str]) -> list[str]:
        return [f"{self.model_name}({item})" for item in batch]


class Tokenizer:
    """分词器。"""

    def __init__(self, vocab_size: int) -> None:
        self.vocab_size = vocab_size
        print(f"  [Tokenizer] Initialized with vocab_size={vocab_size}")

    def tokenize(self, text: str) -> list[int]:
        return [hash(c) % self.vocab_size for c in text.split()]


class MetricsCollector:
    """指标收集器。"""

    def __init__(self) -> None:
        self._count = 0

    def record(self, batch_size: int) -> None:
        self._count += batch_size

    @property
    def total(self) -> int:
        return self._count


class BatchPredictor:
    """批量推理器 — 在分布式场景中需要被序列化到远程 worker。"""

    def __init__(
        self,
        registry: ModelRegistry,
        tokenizer: Tokenizer,
        metrics: MetricsCollector,
    ) -> None:
        self.registry = registry
        self.tokenizer = tokenizer
        self.metrics = metrics

    def __call__(self, batch: list[str]) -> list[str]:
        self.metrics.record(len(batch))
        return self.registry.predict(batch)


class ConfiguredPredictor:
    """使用配置注入的推理器。"""

    def __init__(
        self,
        model_name: Annotated[str, Inject(config="model.name")],
        vocab_size: Annotated[int, Inject(config="model.vocab_size")],
    ) -> None:
        self.model_name = model_name
        self.vocab_size = vocab_size
        print(f"  [ConfiguredPredictor] model={model_name}, vocab={vocab_size}")

    def predict(self, text: str) -> str:
        return f"{self.model_name}: {text}"


# ── 运行示例 ──────────────────────────────────────────────────────


def main() -> None:
    # ── 1. make_injectable：生成可序列化的零参数子类 ──
    print("=== make_injectable ===")
    container = Container()
    container.register(
        ModelRegistry,
        factory=lambda: ModelRegistry("bert-base-uncased"),
        scope=Scope.SINGLETON,
    )
    container.register(
        Tokenizer,
        factory=lambda: Tokenizer(vocab_size=30522),
        scope=Scope.SINGLETON,
    )
    container.register(MetricsCollector, scope=Scope.SINGLETON)

    InjectablePredictor = container.make_injectable(BatchPredictor)
    print(f"  Generated class: {InjectablePredictor.__name__}")
    print(f"  Is subclass? {issubclass(InjectablePredictor, BatchPredictor)}")

    # 模拟序列化到远程 worker（cloudpickle 是 Ray 使用的序列化方式）
    serialized = cloudpickle.dumps(InjectablePredictor)
    print(f"  Serialized size: {len(serialized)} bytes")

    # 模拟在 worker 端反序列化并使用
    RemotePredictor = cloudpickle.loads(serialized)
    print("\n  [Worker] Creating instance (triggers container rebuild):")
    predictor = RemotePredictor()
    results = predictor(["hello world", "foo bar"])
    print(f"  [Worker] Predictions: {results}")

    # ── 2. resolve_kwargs：解析构造参数为字典 ──
    print("\n=== resolve_kwargs ===")
    kwargs = container.resolve_kwargs(BatchPredictor)
    print(f"  Resolved kwargs keys: {list(kwargs.keys())}")
    print(f"  registry model: {kwargs['registry'].model_name}")
    print(f"  tokenizer vocab: {kwargs['tokenizer'].vocab_size}")

    manual_predictor = BatchPredictor(**kwargs)
    results = manual_predictor(["test input"])
    print(f"  Manual predictor result: {results}")

    # ── 3. ContainerRecipe：可序列化快照 ──
    print("\n=== ContainerRecipe ===")
    recipe = container.recipe
    print(f"  Recipe specs: {len(recipe.specs)}")

    recipe_bytes = cloudpickle.dumps(recipe)
    print(f"  Serialized recipe: {len(recipe_bytes)} bytes")

    restored_recipe = cloudpickle.loads(recipe_bytes)
    rebuilt_container = restored_recipe.build()

    print("\n  [Remote] Rebuilding container from recipe:")
    remote_predictor = rebuilt_container.resolve(BatchPredictor)
    results = remote_predictor(["remote test"])
    print(f"  [Remote] Predictions: {results}")

    # ── 4. 配置注入 + Recipe ──
    print("\n=== Config + Recipe ===")
    config_container = Container(config={
        "model": {"name": "bert-base", "vocab_size": 30522},
    })

    config_recipe = config_container.recipe
    config_bytes = cloudpickle.dumps(config_recipe)
    print(f"  Config recipe size: {len(config_bytes)} bytes")

    restored = cloudpickle.loads(config_bytes).build()
    pred = restored.resolve(ConfiguredPredictor)
    print(f"  Prediction: {pred.predict('hello')}")

    # ── 5. 模拟 Ray Data 使用模式 ──
    print("\n=== Simulated Ray Data pattern ===")
    print("  # 模式 1: make_injectable（推荐，支持不可序列化的依赖）")
    print("  # ds.map_batches(")
    print("  #     container.make_injectable(BatchPredictor),")
    print("  #     compute=ray.data.ActorPoolStrategy(size=4),")
    print("  # )")
    print()
    print("  # 模式 2: resolve_kwargs（适用于 fn_constructor_kwargs）")
    print("  # ds.map_batches(")
    print("  #     BatchPredictor,")
    print("  #     fn_constructor_kwargs=container.resolve_kwargs(BatchPredictor),")
    print("  # )")

    print("\n✓ 分布式计算集成示例完成")


if __name__ == "__main__":
    main()
