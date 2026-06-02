"""
User CRUD Handler
==================

对 User 表提供增删改查操作，所有 subject 均设置为仅内部调用。

读写分离说明：
- 写操作（create, update, delete）→ get_db_session_master()
- 读操作（get） → get_db_session_slave()
- 列表操作（list） → get_db_session_slave()（通过 @read_only 装饰器）
- 混合操作（先查后写）→ 全部使用主库会话，避免主从延迟导致数据不一致
"""

import logging
import time

from sqlmodel import select, func

from app.bootstrap import app
from ..listeners import get_db_session, get_db_session_master, get_db_session_slave, read_only
from ..database_models import User
from ..utils.snowflake import snowflake_generator
from models import (
    UserCreateInput,
    UserCreateOutput,
    UserGetInput,
    UserGetOutput,
    UserUpdateInput,
    UserUpdateOutput,
    UserDeleteInput,
    UserDeleteOutput,
    UserListInput,
    UserListOutput,
)

logger = logging.getLogger("chongming.worker.user_auth")


@app.handler("user.create")
async def create_user(input: UserCreateInput) -> UserCreateOutput:
    """
    创建用户（内部调用）
    写操作 → 使用主库会话
    """
    if input.roles is None:
        input.roles = ["user"]

    async for session in get_db_session_master():
        # 使用 Snowflake 算法生成全局唯一 ID
        user_id = snowflake_generator.next_id()

        user = User(
            id=user_id,
            username=input.username,
            password_hash=input.password_hash,
            email=input.email,
            roles=input.roles,
            created_at=time.time(),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        logger.info("创建用户: id=%s, username=%s", user.id, user.username)
        assert user.id is not None, "User ID should not be None after commit"
        assert user.email is not None, "User email should not be None after commit"
        return UserCreateOutput(
            id=user.id,
            username=user.username,
            email=user.email,
            roles=user.roles,
            created_at=time.time(),
        )

    raise RuntimeError("No database session available")


@app.handler("user.get")
async def get_user(input: UserGetInput) -> UserGetOutput:
    """
    根据 ID 获取用户（内部调用）
    读操作 → 使用从库会话
    """
    async for session in get_db_session_slave():
        user = await session.get(User, input.user_id)
        if user is None:
            raise ValueError(f"用户不存在: {input.user_id}")

        assert user.id is not None, "User ID should not be None after fetch"
        assert user.email is not None, "User email should not be None after fetch"
        return UserGetOutput(
            id=user.id,
            username=user.username,
            email=user.email,
            roles=user.roles,
        )

    raise RuntimeError("No database session available")


@app.handler("user.update")
async def update_user(input: UserUpdateInput) -> UserUpdateOutput:
    """
    更新用户信息（内部调用）
    混合操作（先查后写）→ 全部使用主库会话，避免主从延迟
    """
    async for session in get_db_session_master():
        user = await session.get(User, input.user_id)
        if user is None:
            raise ValueError(f"用户不存在: {input.user_id}")

        if input.username is not None:
            user.username = input.username
        if input.email is not None:
            user.email = input.email
        if input.roles is not None:
            user.roles = input.roles
        session.add(user)
        await session.commit()
        await session.refresh(user)

        logger.info("更新用户: id=%s", user.id)
        assert user.id is not None, "User ID should not be None after commit"
        assert user.email is not None, "User email should not be None after commit"
        return UserUpdateOutput(
            id=user.id,
            username=user.username,
            email=user.email,
            roles=user.roles,
        )

    raise RuntimeError("No database session available")


@app.handler("user.delete")
async def delete_user(input: UserDeleteInput) -> UserDeleteOutput:
    """
    删除用户（内部调用）
    写操作 → 使用主库会话
    """
    async for session in get_db_session_master():
        user = await session.get(User, input.user_id)
        if user is None:
            raise ValueError(f"用户不存在: {input.user_id}")

        await session.delete(user)
        await session.commit()

        logger.info("删除用户: id=%s", input.user_id)
        return UserDeleteOutput(
            status=True,
            message=f"用户 {input.user_id} 已删除",
        )

    raise RuntimeError("No database session available")


@app.handler("user.list")
@read_only
async def list_users(input: UserListInput) -> UserListOutput:
    """
    获取用户列表（内部调用）
    读操作 → 使用 @read_only 装饰器自动路由到从库
    """
    async for session in get_db_session():
        # 使用 count + select 获取总数和列表
        # count 查询
        count_stmt = select(func.count()).select_from(User)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

        # 列表查询
        statement = (
            select(User)
            .offset(input.offset)
            .limit(input.limit)
        )
        results = await session.execute(statement)
        users = results.scalars().all()

        return UserListOutput(
            users=[{
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "roles": user.roles,
            } for user in users],
            total=total,
            offset=input.offset,
            limit=input.limit,
        )

    raise RuntimeError("No database session available")
