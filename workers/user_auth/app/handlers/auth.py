"""
用户服务 Handler
=================

提供用户注册、登录、Token 生成等认证相关功能。

网关配置监听
=============
通过 ``@app.on_start`` 和 ``@app.on_stop`` 生命周期钩子，
自动监听 ``_gw_config_`` KV 桶中的 ``gateway_config`` 键变更。
当网关配置（如 JWT 密钥）更新时，实时更新 JWTAuth 实例，无需重启。
"""

import logging
import time

from sqlmodel import select

from app.bootstrap import app
from app.utils.password import hash_password, verify_password
from app.database_models import User, Role, UserRole
from app.utils.snowflake import snowflake_generator
from ..listeners import get_jwt_auth, get_db_session_master, get_db_session_slave

from models import (
    UserAuthInput,
    UserAuthOutput,
    UserLoginInput,
    UserLoginOutput,
    UserRegisterInput,
    UserRegisterOutput,
)


logger = logging.getLogger("chongming.worker.user_auth")


@app.handler("user.auth")
async def auth_user(input: UserAuthInput) -> UserAuthOutput:
    """为用户生成 JWT Token（内部调用）

    通常被其他服务通过 ``_app.request()`` 调用，
    用于为用户签发访问令牌。
    """
    jwt_auth = await get_jwt_auth()
    token = jwt_auth.create_token({
        "sub": input.user_id,
        "roles": input.roles,
        "username": input.username,
        "email": input.email,
        "other": input.other
    })
    status = token is not None
    return UserAuthOutput(
        status=status,
        token=str(token) if token else "",
        timestamp=time.time()
    )


@app.handler("user.register")
async def register_user(input: UserRegisterInput) -> UserRegisterOutput:
    """用户注册（对外接口）

    接收用户名、密码和邮箱，完成以下流程：
    1. 检查用户名是否已被注册
    2. 对密码进行 argon2 哈希
    3. 在数据库中创建用户记录
    4. 为用户签发 JWT Token
    5. 返回注册结果及 Token
    """
    # 参数校验
    if not input.username or len(input.username.strip()) == 0:
        raise ValueError("用户名不能为空")
    if not input.password or len(input.password) < 6:
        raise ValueError("密码长度不能少于 6 位")

    username = input.username.strip()

    async for session in get_db_session_master():
        # 检查用户名是否已存在
        stmt = select(User).where(User.username == username)
        result = await session.execute(stmt)
        existing_user = result.scalar_one_or_none()
        if existing_user is not None:
            raise ValueError(f"用户名 '{username}' 已被注册")

        # 哈希密码
        password_hash = hash_password(input.password)

        # 使用 Snowflake 算法生成全局唯一 ID
        user_id = snowflake_generator.next_id()

        # 创建用户
        user = User(
            id=user_id,
            username=username,
            password_hash=password_hash,
            email=input.email or "",
            roles=["user"],
            created_at=time.time(),
        )
        session.add(user)
        await session.flush()

        # 自动分配默认 "user" 角色
        role_stmt = select(Role).where(Role.name == "user")
        role_result = await session.execute(role_stmt)
        default_role = role_result.scalar_one_or_none()
        if default_role is not None:
            ur = UserRole(user_id=user.id, role_id=default_role.id) # type: ignore
            session.add(ur)

        await session.commit()
        await session.refresh(user)

        logger.info("新用户注册成功: id=%s, username=%s", user.id, user.username)

        # 签发 Token
        jwt_auth = await get_jwt_auth()
        user_id = user.id
        assert user_id is not None, "User ID should not be None after commit"
        token = jwt_auth.create_token({
            "sub": str(user_id),
            "username": user.username,
            "roles": user.roles,
            "email": user.email or "",
        })

        return UserRegisterOutput(
            status=True,
            token=str(token) if token else "",
            user_id=user_id,
            username=user.username,
            email=user.email or "",
            roles=user.roles,
            timestamp=time.time(),
        )

    raise RuntimeError("No database session available")


@app.handler("user.login")
async def login_user(input: UserLoginInput) -> UserLoginOutput:
    """用户登录（对外接口）

    接收用户名和密码，完成以下流程：
    1. 根据用户名从数据库查找用户
    2. 验证密码是否匹配
    3. 为用户签发 JWT Token
    4. 返回登录结果及 Token
    """
    if not input.user_name or not input.password:
        raise ValueError("用户名和密码不能为空")

    async for session in get_db_session_slave():
        # 查询用户
        stmt = select(User).where(User.username == input.user_name)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            logger.warning("登录失败: 用户 '%s' 不存在", input.user_name)
            raise ValueError("用户名或密码错误")

        # 验证密码
        if not verify_password(input.password, user.password_hash):
            logger.warning("登录失败: 用户 '%s' 密码错误", input.user_name)
            raise ValueError("用户名或密码错误")

        # 生成 Token
        jwt_auth = await get_jwt_auth()
        user_id = user.id
        user_email = user.email or ""
        assert user_id is not None, "User ID should not be None"
        token = jwt_auth.create_token({
            "sub": str(user_id),
            "username": user.username,
            "roles": user.roles,
            "email": user_email,
        })

        logger.info("用户登录成功: id=%s, username=%s", user_id, user.username)
        return UserLoginOutput(
            status=True,
            token=str(token) if token else "",
            user_id=str(user_id),
            username=user.username,
            email=user_email,
            other={},
            roles=",".join(user.roles) if isinstance(user.roles, list) else user.roles,
            timestamp=time.time(),
        )

    raise RuntimeError("No database session available")
