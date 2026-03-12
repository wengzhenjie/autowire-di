"""配置注入示例

演示通过 Inject 标记从配置字典中注入值，支持点号路径和嵌套结构。
"""

from __future__ import annotations

from typing import Annotated

from autowire_di import Container, Inject


# ── 使用配置注入的服务类 ──────────────────────────────────────────


class DatabaseConnection:
    """数据库连接，从配置中注入连接参数。"""

    def __init__(
        self,
        host: Annotated[str, Inject(config="database.host")],
        port: Annotated[int, Inject(config="database.port")],
        name: Annotated[str, Inject(config="database.name")],
    ) -> None:
        self.host = host
        self.port = port
        self.name = name

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.host}:{self.port}/{self.name}"


class CacheClient:
    """缓存客户端，从配置中注入 TTL 和前缀。"""

    def __init__(
        self,
        ttl: Annotated[int, Inject(config="cache.ttl")],
        prefix: Annotated[str, Inject(config="cache.key_prefix")],
    ) -> None:
        self.ttl = ttl
        self.prefix = prefix

    def make_key(self, key: str) -> str:
        return f"{self.prefix}:{key}"


class AppService:
    """组合服务，同时依赖数据库连接和缓存客户端。"""

    def __init__(
        self,
        db: DatabaseConnection,
        cache: CacheClient,
        app_name: Annotated[str, Inject(config="app.name")],
    ) -> None:
        self.db = db
        self.cache = cache
        self.app_name = app_name

    def info(self) -> dict:
        return {
            "app": self.app_name,
            "database": self.db.dsn,
            "cache_ttl": self.cache.ttl,
        }


# ── 运行示例 ──────────────────────────────────────────────────────


def main() -> None:
    container = Container()

    # 设置嵌套配置
    container.set_config({
        "app": {
            "name": "my-awesome-app",
            "version": "1.0.0",
        },
        "database": {
            "host": "localhost",
            "port": 5432,
            "name": "mydb",
        },
        "cache": {
            "ttl": 300,
            "key_prefix": "app",
        },
    })

    # 解析 — 配置值通过 Inject 标记自动注入
    db = container.resolve(DatabaseConnection)
    print(f"Database DSN: {db.dsn}")
    assert db.host == "localhost"
    assert db.port == 5432

    cache = container.resolve(CacheClient)
    print(f"Cache key example: {cache.make_key('user:1')}")
    assert cache.ttl == 300

    # 组合服务也能正确注入
    app = container.resolve(AppService)
    print(f"App info: {app.info()}")
    assert app.app_name == "my-awesome-app"

    print("\n✓ 配置注入示例完成")


if __name__ == "__main__":
    main()
