# python-di

一个 Pythonic 的依赖注入框架，支持自动装配（auto-wiring）、作用域生命周期管理和异步解析。

专为需要将 DI 容器序列化到远程 worker（如 Ray Data、Spark UDF）的分布式计算场景设计。

## 安装

```bash
uv add python-di
```

## 快速开始

### 基本注册与解析

```python
from python_di import Container, Scope

container = Container()

# 接口 -> 实现
container.register(OrderRepository, PostgresOrderRepository)

# 单例生命周期
container.register(DatabasePool, PostgresPool, scope=Scope.SINGLETON)

# 自动装配：根据 __init__ 类型注解自动解析依赖
service = container.resolve(OrderService)
```

### 自动装配

容器通过检查 `__init__` 的类型注解自动构建依赖图，无需手动连接：

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class UserRepository(Protocol):
    def find(self, user_id: int) -> dict: ...

class PostgresUserRepository:
    def find(self, user_id: int) -> dict:
        return {"id": user_id}

class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

container = Container()
container.register(UserRepository, PostgresUserRepository)

# UserService 未注册，但容器能通过类型注解自动构造它
service = container.resolve(UserService)
assert isinstance(service.repo, PostgresUserRepository)
```

### 三种作用域

```python
from python_di import Container, Scope

container = Container()

# TRANSIENT（默认）：每次 resolve 创建新实例
container.register(RequestHandler, scope=Scope.TRANSIENT)

# SINGLETON：全局唯一实例，线程安全
container.register(DatabasePool, PostgresPool, scope=Scope.SINGLETON)

# SCOPED：在同一作用域内共享实例，不同作用域间隔离
container.register(DbSession, scope=Scope.SCOPED)

with container.new_scope() as scope:
    s1 = scope.resolve(DbSession)
    s2 = scope.resolve(DbSession)
    assert s1 is s2  # 同一作用域内是同一实例

with container.new_scope() as scope2:
    s3 = scope2.resolve(DbSession)
    assert s3 is not s1  # 不同作用域是不同实例
```

### 三种注册方式

```python
container = Container()

# 1. 类注册（ClassProvider）：自动装配 __init__
container.register(ICache, RedisCache)

# 2. 工厂函数（FactoryProvider）：自定义构造逻辑
container.register(ICache, factory=lambda: RedisCache(host="localhost"))

# 3. 实例注册（ValueProvider）：直接绑定已有对象
cache = RedisCache(host="localhost")
container.register(ICache, instance=cache)
```

### 命名绑定

同一接口注册多个实现，通过名称区分：

```python
from typing import Annotated
from python_di import Container, Named

container = Container()
container.register(ICache, RedisCache, name="primary")
container.register(ICache, MemoryCache, name="fallback")

# 手动按名称解析
primary = container.resolve(ICache, name="primary")

# 或通过 Annotated 标记自动注入
class OrderService:
    def __init__(
        self,
        cache: Annotated[ICache, Named("primary")],
        fallback: Annotated[ICache, Named("fallback")],
    ) -> None:
        self.cache = cache
        self.fallback = fallback
```

### 配置注入

通过 `Inject` 标记从配置字典中注入值，支持点号路径：

```python
from typing import Annotated
from python_di import Container, Inject

container = Container()
container.set_config({
    "db": {"host": "localhost", "port": 5432},
    "cache": {"ttl": 300},
})

class DbConnection:
    def __init__(
        self,
        host: Annotated[str, Inject(config="db.host")],
        port: Annotated[int, Inject(config="db.port")],
    ) -> None:
        self.host = host
        self.port = port

conn = container.resolve(DbConnection)
assert conn.host == "localhost"
assert conn.port == 5432
```

### 多重绑定

同一接口注册多个实现，一次性全部解析：

```python
container = Container()
container.register_multi(EventHandler, LoggingHandler)
container.register_multi(EventHandler, MetricsHandler)
container.register_multi(EventHandler, AlertHandler)

# 解析为列表
handlers = container.resolve_multi(EventHandler)  # [LoggingHandler, MetricsHandler, AlertHandler]

# 也可以通过 list[T] 类型注解自动注入
class EventBus:
    def __init__(self, handlers: list[EventHandler]) -> None:
        self.handlers = handlers
```

### 模块系统

将相关绑定组织为可复用的模块：

```python
from python_di import Container, Module, Scope

class InfraModule(Module):
    def configure(self, container: Container) -> None:
        container.register(DatabasePool, PostgresPool, scope=Scope.SINGLETON)
        container.register(ICache, RedisCache, scope=Scope.SINGLETON)
        container.register(MessageQueue, RabbitMQ)

class DomainModule(Module):
    def configure(self, container: Container) -> None:
        container.register(UserRepository, PostgresUserRepository)
        container.register(OrderRepository, PostgresOrderRepository)

container = Container()
container.install(InfraModule())
container.install(DomainModule())
```

### 工厂函数与资源清理

生成器工厂支持 teardown 逻辑——yield 之前的代码创建资源，yield 之后的代码在作用域结束时清理：

```python
def create_db_session(pool: DatabasePool) -> Generator[DbSession, None, None]:
    session = pool.acquire()
    yield session
    session.close()  # 作用域结束时自动执行

container.register(DbSession, factory=create_db_session, scope=Scope.SCOPED)

with container.new_scope() as scope:
    session = scope.resolve(DbSession)
    # 使用 session ...
# 离开 with 块时自动调用 session.close()
```

异步生成器同样支持：

```python
async def create_async_session(pool: AsyncPool) -> AsyncGenerator[AsyncSession, None]:
    session = await pool.acquire()
    yield session
    await session.close()

container.register(AsyncSession, factory=create_async_session, scope=Scope.SCOPED)

async with container.new_async_scope() as scope:
    session = await scope.async_resolve(AsyncSession)
```

### 子容器

创建子容器继承父容器的绑定，可独立覆盖：

```python
parent = Container()
parent.register(ICache, RedisCache)

child = parent.create_child()
child.override(ICache, MemoryCache)  # 仅在子容器中生效

parent.resolve(ICache)  # -> RedisCache
child.resolve(ICache)   # -> MemoryCache
```

### 启动时验证

在应用启动时一次性验证所有绑定，提前发现缺失依赖、循环依赖和作用域不匹配：

```python
container = Container()
container.register(UserService)  # 依赖 UserRepository，但未注册
container.register(CacheService, scope=Scope.SINGLETON)
# CacheService 依赖 DbSession(SCOPED) -> 单例不能依赖作用域服务

container.validate()  # 抛出 ValidationError，包含所有错误
```

检测的问题类型：
- **缺失绑定**：依赖的接口未注册
- **循环依赖**：A -> B -> C -> A
- **作用域不匹配**：长生命周期服务依赖短生命周期服务（如 Singleton 依赖 Scoped）

## 分布式计算集成

### 核心问题

在 Ray Data、Spark 等分布式框架中，用户类需要被序列化后发送到远程 worker。但 DI 容器持有的活跃对象（数据库连接、模型权重、线程锁）无法安全序列化。

### `make_injectable`：零参数子类

`make_injectable` 生成一个零参数子类，内部仅捕获可序列化的 **recipe**（注册指令的纯数据快照），在 worker 端延迟重建容器并解析依赖：

```python
container = Container(config={"model": {"name": "bert-base", "device": "cuda"}})
container.register(ModelRegistry, HuggingFaceRegistry)
container.register(Tokenizer)
container.register(MetricsCollector)

# 生成零参数子类
InjectablePredictor = container.make_injectable(TorchPredictor)

# 可以用 overrides 固定特定参数
InjectablePredictor = container.make_injectable(TorchPredictor, device="cpu")
```

与 Ray Data 配合使用：

```python
import ray.data

ds = ray.data.read_csv("data.csv")
ds.map_batches(
    container.make_injectable(TorchPredictor),
    compute=ray.data.ActorPoolStrategy(size=4),
    num_gpus=1,
)
```

### `resolve_kwargs`：手动构造参数

对于需要 `fn_constructor_kwargs` 的场景：

```python
kwargs = container.resolve_kwargs(TorchPredictor)
# kwargs = {"registry": HuggingFaceRegistry(), "tokenizer": Tokenizer(), ...}

# 适用于 Ray Data 的 fn_constructor_kwargs 模式
ds.map_batches(
    TorchPredictor,
    fn_constructor_kwargs=container.resolve_kwargs(TorchPredictor),
)
```

### `ContainerRecipe`：可序列化快照

Recipe 是容器注册指令的纯数据快照，可安全通过 cloudpickle 序列化：

```python
import cloudpickle

recipe = container.recipe

# 序列化到远程 worker
data = cloudpickle.dumps(recipe)
restored_recipe = cloudpickle.loads(data)

# 在 worker 端重建完整容器
rebuilt = restored_recipe.build()
service = rebuilt.resolve(TorchPredictor)
```

### `make_injectable` vs `resolve_kwargs`

| | `make_injectable` | `resolve_kwargs` |
|---|---|---|
| 序列化内容 | Recipe（注册指令） | 已创建的实例 |
| 含不可序列化依赖 | 可以（延迟重建） | 不行（会失败） |
| 适用场景 | Ray `map_batches(cls=)` | Ray `fn_constructor_kwargs` |
| 实例创建时机 | worker 端首次构造时 | 调用方立即创建 |

## 异常类型

| 异常 | 触发场景 |
|---|---|
| `ResolutionError` | 未注册的接口、缺失的配置键 |
| `CircularDependencyError` | 检测到循环依赖链 |
| `RegistrationError` | 重复注册（未使用 override） |
| `ScopeMismatchError` | 长生命周期服务依赖短生命周期服务 |
| `ScopeNotActiveError` | 在作用域外解析 SCOPED 服务 |
| `ValidationError` | `validate()` 发现一个或多个错误 |

## 项目结构

```
src/python_di/
├── __init__.py       # 公开 API 导出
├── container.py      # Container 和 ScopedContainer
├── resolver.py       # 自动装配解析器（类型注解检查）
├── registry.py       # 绑定存储（单绑定 + 多重绑定）
├── providers.py      # ClassProvider / FactoryProvider / ValueProvider / AliasProvider
├── types.py          # Scope 枚举、Binding 数据类、异常层次
├── markers.py        # Annotated 标记：Named、Inject
├── module.py         # Module 基类
├── scope.py          # SingletonCache（线程安全）、ScopedCache
├── recipe.py         # ContainerRecipe：可序列化的容器快照
└── validator.py      # 启动时依赖图静态验证
```

## 开发

```bash
# 安装开发依赖
uv sync

# 运行测试
uv run pytest

# 类型检查
uv run mypy src/

# 代码检查
uv run ruff check src/ tests/
```

## License

MIT
