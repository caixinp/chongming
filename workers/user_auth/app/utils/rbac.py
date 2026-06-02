"""
RBAC 种子数据初始化模块
========================

提供权限和角色的种子数据，用于 Worker 启动时初始化及运行时同步。

**权限动态生成策略：**
权限数据不再硬编码，而是从网关的 ``_gw_routes_`` KV 桶动态读取。
该桶中存储了**所有 worker 注册的所有路由**（含 internal 标记）。
我们只将非 internal 的路由转换为权限记录。

**数据源：**
- ``_gw_routes_`` KV 桶（NATS JetStream）— 网关维护的所有 worker 的路由注册表
- 每个路由条目包含 subject（如 ``user.login``）、path、method、internal 标记等
- subject 天然是 ``{resource}.{action}`` 格式，直接映射为权限名

**同步机制：**
1. 启动时：读取 ``_gw_routes_`` 全量数据，同步缺失的权限
2. 运行时：订阅 ``_gw_routes_`` KV 桶变更，新路由注册时立即补齐权限
   （事件驱动，无需定时轮询）

**注意：** 权限校验相关的 ``require_permission`` 装饰器
和 ``get_user_permissions`` 函数已移至 ``chongming-permission``
工具包（``from chongming_permission import require_permission``）。
"""

import logging
from typing import List, Dict, Any, Optional, Set
import json

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database_models import Role, Permission, RolePermission
from chongming_cache import ChongmingCache


logger = logging.getLogger("chongming.worker.user_auth")

# ── 常量 ──────────────────────────────────────────────────────

_GW_ROUTES_BUCKET = "_gw_routes_"  # 网关路由 KV 桶名


# ── 从网关 KV 读取所有已注册路由 ──────────────────────────────


async def _load_all_routes_from_gw(kv_cache: ChongmingCache) -> List[Dict[str, Any]]:
    """从网关的 ``_gw_routes_`` KV 桶读取所有注册路由

    返回所有非 internal 路由条目（即需要对外暴露 HTTP 接口的）。
    internal 路由仅用于 Worker 间通讯，不需要对应权限。

    Args:
        kv_cache: 已连接到 ``_gw_routes_`` 桶的 ChongmingCache 实例

    Returns:
        路由信息字典列表，每项至少包含::
            {
                "subject": "user.login",       # 用于生成权限名
                "method": "POST",
                "path": "/user/login",
                "internal": False,
                "router_prefix": "/user_auth",
                "tags": ["user_auth"],
                "summary": "用户登录",
            }
    """
    try:
        keys = await kv_cache.keys()
    except Exception as e:
        logger.error("读取网关路由 KV 桶失败: %s", e)
        return []

    routes: List[Dict[str, Any]] = []
    seen_subjects: Set[str] = set()

    for key in keys:
        try:
            entry = await kv_cache.get(key)
            if entry is None or entry.value is None:
                continue

            info = json.loads(entry.value.decode())
            subject = info.get("subject", key)

            # ⚠️ 兼容性修复：如果 KV 中存储的 route_info 缺少 "subject" 字段
            # （旧版网关注册时未存入 subject），注入 KV key 作为 subject
            if "subject" not in info:
                info["subject"] = subject

            # 跳过 internal=true 的路由（仅 Worker 间通讯）
            if info.get("internal", False):
                continue

            if subject in seen_subjects:
                continue
            seen_subjects.add(subject)

            # 维持与旧版 _parse_permissions_from_config 一致的 subject 格式校验
            if "." not in subject:
                logger.warning("路由 subject '%s' 格式无效（缺少 '.'），跳过", subject)
                continue

            routes.append(info)
            logger.debug("  读取路由: %s (prefix=%s, internal=%s)",
                         subject, info.get("router_prefix"), info.get("internal"))

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("解析路由 KV 条目 '%s' 失败: %s", key, e)
            continue

    logger.info(
        "从网关读取 %d 个已注册路由（共 %d 个 key）",
        len(routes), len(keys),
    )
    return routes


def _routes_to_permissions(routes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """将路由信息转换为权限字典列表

    每个路由的 subject 格式应为 ``{resource}.{action}``。

    Args:
        routes: 路由信息列表（从 ``_gw_routes_`` KV 桶读取）

    Returns:
        权限字典列表，每项格式::
            {
                "name": "user.login",
                "resource": "user",
                "action": "login",
                "description": "用户登录",
            }
    """
    permissions: List[Dict[str, str]] = []

    for route in routes:
        subject: str = route.get("subject", "")

        # 解析 subject → resource.action
        parts = subject.split(".", 1)
        if len(parts) != 2 or not parts[0]:
            logger.warning("路由 subject '%s' 格式无效: 必须为 '{resource}.{action}' 格式，跳过", subject)
            continue

        resource, action = parts

        # description 优先级：summary > 自动生成
        summary = route.get("summary", "") or ""
        description = summary if summary else f"{resource} {action}"

        permissions.append({
            "name": subject,
            "resource": resource,
            "action": action,
            "description": description,
        })

    return permissions


# ── 运行时权限同步 ──────────────────────────────────────────────


async def sync_missing_permissions(session: AsyncSession, kv_cache: ChongmingCache) -> int:
    """运行时同步：从网关 KV 读取所有已注册路由，创建缺失的权限

    幂等操作，可安全地多次调用。
    只增不删：不会删除数据库中有但路由中已移除的权限，
    避免意外破坏已有角色的权限绑定。

    在以下场景调用：
    - Worker 启动时：读取全量路由同步
    - 网关路由变更时（通过 subscribe 事件驱动）：增量同步

    Args:
        session: 数据库会话
        kv_cache: 已连接到 ``_gw_routes_`` 桶的 ChongmingCache 实例

    Returns:
        本次新增的权限数量
    """
    # 1. 从网关 KV 读取所有已注册的非 internal 路由
    routes = await _load_all_routes_from_gw(kv_cache)
    if not routes:
        logger.warning("网关 KV 桶中无可用的非 internal 路由，跳过权限同步")
        return 0

    # 2. 转换为权限定义
    permission_defs = _routes_to_permissions(routes)
    if not permission_defs:
        return 0

    logger.info("开始同步权限（从 %d 个已注册路由生成 %d 个权限）...",
                len(routes), len(permission_defs))

    # 3. 创建数据库中缺失的权限
    created_count = 0
    for pd in permission_defs:
        stmt = select(Permission).where(Permission.name == pd["name"])
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            perm = Permission(**pd)  # type: ignore
            session.add(perm)
            created_count += 1
            logger.info("  新增权限: %s (resource=%s, action=%s)",
                        pd["name"], pd["resource"], pd["action"])

    if created_count > 0:
        await session.commit()
        logger.info("权限同步完成: 新增 %d 个权限", created_count)
    else:
        logger.debug("权限同步: 无新增，所有路由对应的权限已存在")

    return created_count


# ── 事件驱动：订阅网关路由变更 ────────────────────────────────


async def _on_routes_change(entry: Any, session_getter):
    """路由变更回调：当网关 KV 桶中路由发生变化时，自动同步权限

    此回调由 ``subscribe_routes_permission_sync()`` 注册，
    在网关 KV 桶 ``_gw_routes_`` 中的任何路由变更事件触发。

    Args:
        entry: KeyValue.Entry — 变更的路由条目
        session_getter: 异步生成器函数，用于获取数据库会话
    """
    if entry is None or entry.value is None:
        # 路由被删除，无需处理（只增不删策略）
        return

    try:
        info = json.loads(entry.value.decode())
    except json.JSONDecodeError:
        return

    # 跳过 internal 路由
    if info.get("internal", False):
        return

    subject = info.get("subject", entry.key)
    if not subject or "." not in subject:
        return

    # 创建或跳过该权限
    parts = subject.split(".", 1)
    resource, action = parts
    summary = info.get("summary", "") or ""
    description = summary if summary else f"{resource} {action}"

    permission_def = {
        "name": subject,
        "resource": resource,
        "action": action,
        "description": description,
    }

    async for session in session_getter():
        try:
            stmt = select(Permission).where(Permission.name == subject)
            result = await session.execute(stmt)
            if result.scalar_one_or_none() is None:
                perm = Permission(**permission_def)  # type: ignore
                session.add(perm)
                await session.commit()
                logger.info("事件驱动: 新增权限 %s (路由注册触发)", subject)
        except Exception as e:
            logger.warning("事件驱动权限同步失败 (%s): %s", subject, e)


async def subscribe_routes_permission_sync(app, session_getter) -> None:
    """订阅网关路由 KV 桶变更，实现运行时权限自动同步

    在 Worker 启动时调用（通过 ``@app.on_start`` 钩子）。
    当任何 worker 注册新路由到网关时，网关会更新 ``_gw_routes_`` KV 桶，
    subscribe 立即收到变更通知，自动创建对应的权限记录。

    这是一个**事件驱动**的机制，**不是定时轮询**。

    Args:
        app: WorkerLifespan 实例（用于获取 NATS 连接）
        session_getter: 异步生成器函数，返回 ``AsyncSession`` 用于数据库操作
    """
    try:
        kv_cache = ChongmingCache(logger, bucket=_GW_ROUTES_BUCKET)
        await kv_cache.connect()

        # 定义路由变更回调
        async def _callback(entry):
            await _on_routes_change(entry, session_getter)

        # 订阅所有路由键的变更（> 通配符匹配所有键）
        await kv_cache.subscribe(">", _callback)
        logger.info(
            "已订阅网关路由变更（bucket=%s），运行时权限自动同步已启用",
            _GW_ROUTES_BUCKET,
        )
    except Exception as e:
        logger.warning("订阅网关路由变更失败（不影响 worker 主流程）: %s", e)


# ── 默认角色定义 ──────────────────────────────────────────────

# 角色权限映射规则说明：
# - 用 subject 名称（即最终的 permission.name）来定义角色拥有的权限
# - subject 名称来自网关 ``_gw_routes_`` KV 桶中非 internal 的路由
# - superadmin 自动拥有**所有**已注册的非 internal 权限

DEFAULT_ROLES = [
    {
        "name": "superadmin",
        "description": "超级管理员（拥有所有权限）",
        "is_system": True,
        "permissions": "__ALL__",  # 特殊标记：表示所有已注册的权限
    },
    {
        "name": "admin",
        "description": "管理员",
        "is_system": True,
        "permissions": [
            # 用户管理（公开接口）
            "user.login", "user.register",
            # 角色管理
            "role.create", "role.get", "role.update", "role.delete", "role.list",
            "role.assign_permission", "role.revoke_permission",
            # 权限管理
            "permission.create", "permission.list", "permission.delete",
            # 用户角色分配
            "userrole.assign", "userrole.revoke", "userrole.list",
        ],
    },
    {
        "name": "user",
        "description": "普通用户",
        "is_system": True,
        "permissions": [
            "user.login", "user.register",
            "userrole.list",
        ],
    },
]


# ── 种子数据初始化（启动时调用） ──────────────────────────────


async def seed_default_rbac(
    session: AsyncSession,
    kv_cache: ChongmingCache,
    config_path: str = "",
) -> None:
    """从网关 KV 初始化默认角色和权限（启动时调用）

    与 ``sync_missing_permissions`` 的区别：
    此函数还会创建默认角色及其权限绑定（角色仅创建一次），
    而 ``sync_missing_permissions`` 仅负责运行时补齐新的权限条目。

    Args:
        session: 数据库会话
        kv_cache: 已连接到 ``_gw_routes_`` 桶的 ChongmingCache 实例
        config_path: 保留参数，向下兼容，现已被 KV 桶替代
    """
    # 1. 同步所有已注册路由对应的权限
    routes = await _load_all_routes_from_gw(kv_cache)
    if not routes:
        logger.warning("网关 KV 桶中无可用的非 internal 路由，跳过 RBAC 初始化")
        return

    permission_defs = _routes_to_permissions(routes)
    logger.info("开始初始化 RBAC 数据（基于 %d 个已注册路由的 %d 个权限）...",
                len(routes), len(permission_defs))

    # 2. 创建/同步所有权限
    permission_map: dict[str, Permission] = {}
    for pd in permission_defs:
        stmt = select(Permission).where(Permission.name == pd["name"])
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            perm = Permission(**pd)  # type: ignore
            session.add(perm)
            await session.flush()
            permission_map[pd["name"]] = perm
            logger.debug("  创建权限: %s", pd["name"])
        else:
            permission_map[pd["name"]] = existing

    # 3. 创建角色
    all_permission_names = [pd["name"] for pd in permission_defs]

    for rd in DEFAULT_ROLES:
        stmt = select(Role).where(Role.name == rd["name"])
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            role = Role(
                name=rd["name"],
                description=rd["description"],
                is_system=rd["is_system"],
            )
            session.add(role)
            await session.flush()
            logger.debug("  创建角色: %s", rd["name"])
        else:
            role = existing

        # 4. 确定该角色应拥有的权限
        if rd["permissions"] == "__ALL__":
            perm_names = all_permission_names
        else:
            perm_names = [n for n in rd["permissions"] if n in permission_map]

        # 5. 分配角色权限
        for perm_name in perm_names:
            perm = permission_map.get(perm_name)
            if perm is None:
                continue
            rp_stmt = select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == perm.id,
            )
            rp_result = await session.execute(rp_stmt)
            if rp_result.scalar_one_or_none() is None:
                rp = RolePermission(role_id=role.id, permission_id=perm.id)  # type: ignore
                session.add(rp)

    await session.commit()
    logger.info("RBAC 数据初始化完成（基于网关 KV 路由注册表）")
