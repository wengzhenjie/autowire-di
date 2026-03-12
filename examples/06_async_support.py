"""异步支持示例

演示 async_resolve、异步工厂函数和异步作用域。
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Generator

from autowire_di import Container, Scope


# ── 模拟异步服务 ──────────────────────────────────────────────────


class DatabasePool:
    """模拟数据库连接池（同步创建，异步使用）。"""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        print(f"  [Pool] Created for {self.dsn}")

    def close(self) -> None:
        print(f"  [Pool] Closed for {self.dsn}")


class AsyncSession:
    """模拟异步数据库会话。"""

    _counter = 0

    def __init__(self, pool: DatabasePool) -> None:
        AsyncSession._counter += 1
        self.session_id = AsyncSession._counter
        self.pool = pool
        print(f"  [Session #{self.session_id}] Created")

    async def query(self, sql: str) -> list[dict]:
        await asyncio.sleep(0.01)
        return [{"result": f"data from session #{self.session_id}"}]

    async def close(self) -> None:
        print(f"  [Session #{self.session_id}] Closed")


# ── 工厂函数 ──────────────────────────────────────────────────────


def create_pool() -> Generator[DatabasePool, None, None]:
    """同步生成器工厂：yield 前创建资源，yield 后清理。"""
    pool = DatabasePool(dsn="postgresql://localhost/mydb")
    yield pool
    pool.close()


async def create_session(pool: DatabasePool) -> AsyncGenerator[AsyncSession, None]:
    """异步生成器工厂：从池中获取会话，作用域结束时关闭。"""
    session = AsyncSession(pool)
    yield session
    await session.close()


# ── 业务服务 ──────────────────────────────────────────────────────


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_users(self) -> list[dict]:
        return await self.session.query("SELECT * FROM users")


# ── 运行示例 ──────────────────────────────────────────────────────


async def main() -> None:
    container = Container()

    # 同步工厂 + Singleton：连接池全局唯一
    container.register(
        DatabasePool,
        factory=create_pool,
        scope=Scope.SINGLETON,
    )

    # 异步工厂 + Scoped：会话在作用域内共享
    container.register(
        AsyncSession,
        factory=create_session,
        scope=Scope.SCOPED,
    )

    # ── 异步作用域 1 ──
    print("=== Async Scope 1 ===")
    async with container.new_async_scope() as scope:
        session1 = await scope.async_resolve(AsyncSession)
        session2 = await scope.async_resolve(AsyncSession)
        assert session1 is session2
        print(f"  Same session? {session1 is session2}")

        result = await session1.query("SELECT 1")
        print(f"  Query result: {result}")

        # UserService 也能在异步作用域中解析
        user_svc = await scope.async_resolve(UserService)
        users = await user_svc.get_users()
        print(f"  Users: {users}")
    # 离开作用域时自动 close session

    # ── 异步作用域 2 ──
    print("\n=== Async Scope 2 ===")
    async with container.new_async_scope() as scope2:
        session3 = await scope2.async_resolve(AsyncSession)
        assert session3 is not session1
        print(f"  Different session? {session3 is not session1}")

        # 连接池是同一个 Singleton
        pool1 = await scope2.async_resolve(DatabasePool)
        print(f"  Pool DSN: {pool1.dsn}")
    # 离开作用域时自动 close session

    # ── 清理 Singleton 资源 ──
    print("\n=== Dispose ===")
    await container.async_dispose()

    print("\n✓ 异步支持示例完成")


if __name__ == "__main__":
    asyncio.run(main())
