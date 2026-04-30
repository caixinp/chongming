from sqlalchemy.orm import selectinload
from sqlmodel import select

from ..core.logger import get_logger
from ..constant.permission import PermissionConstant
from ..service.user import UserService
from ..service.role import RoleService
from ..service.permission import PermissionService
from ..model.role import Role
from ..model.user import User

from plugins.scheduler.scheduler import get_task_service_instance


logger = get_logger("scheduler")

# ──────────────────────────────────────────────
# 默认角色定义
# ──────────────────────────────────────────────

# 角色名称常量
ROLE_ADMIN = "admin"        # 超级管理员 - 拥有所有权限
ROLE_MANAGER = "manager"    # 经理 - 拥有业务模块完整操作权限
ROLE_OPERATOR = "operator"  # 操作员 - 拥有业务模块基本操作权限
ROLE_VIEWER = "viewer"      # 访客 - 仅有读取权限


async def init_permission(session):
    """
    初始化系统权限数据

    遍历所有预定义的权限常量，检查数据库中是否已存在对应权限记录。
    对于不存在的权限，创建新的权限记录并关联对应的资源和操作类型，
    同时使用 permission_description_dict 中的描述信息设置 description 字段。

    Args:
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        None

    Note:
        - 权限格式为"resource:action"，例如"user:create"
        - 使用冒号分隔资源和操作，如果缺少操作部分则默认为空字符串
        - 已存在的权限会被跳过，避免重复创建
        - 每个新创建的权限都会记录到日志中
        - 描述信息从 PermissionConstant.get_description_map() 获取
    """
    description_map = PermissionConstant.get_description_map()
    for permission in PermissionConstant.get_all():
        parts = permission.split(":", 1)
        resource = parts[0]
        action = parts[1] if len(parts) > 1 else ""

        existing_permission = await PermissionService.get_permission_by_name(
            session, permission
        )
        if existing_permission:
            logger.debug(f"权限已存在: {permission}")
            continue

        description = description_map.get(permission, None)
        await PermissionService.create_permission(
            session, permission, resource, action, description=description
        )
        logger.info(f"创建权限: {permission} - {description}")

async def dev_init_admin(session):
    """
    初始化系统管理员用户

    检查是否存在邮箱为"admin"的管理员用户，如果不存在则创建一个新的超级管理员账户。
    该函数用于系统首次部署时的管理员账户初始化。

    Args:
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        None

    Note:
        - 默认管理员邮箱和密码均为"admin"
        - 如果管理员已存在，则跳过创建并记录日志
        - 新创建的用户具有超级管理员权限（is_superuser=True）
    """
    # 先检查 admin@qq.com 邮箱是否已被使用
    admin_user = await UserService.get_user_by_email("admin@qq.com", session)
    if admin_user:
        logger.info("管理员用户已存在")
        return
    # 再检查 "admin" 邮箱（兼容旧版初始化逻辑）
    admin_user = await UserService.get_user_by_email("admin", session)
    if admin_user:
        logger.info("管理员用户已存在")
        return
    user = await UserService.create_user(session, "admin@qq.com", "admin", is_superuser=True)
    admin_role = await RoleService.get_role_by_name(session, ROLE_ADMIN)
    if admin_role is None or admin_role.id is None:
        raise ValueError("管理员未创建")
    await RoleService.assign_role_to_user(session, user.id, admin_role.id)


def _get_admin_permissions() -> list:
    """
    获取管理员角色的所有权限 - 包含系统中定义的全部权限。

    Returns:
        list[str]: 所有权限名称列表
    """
    return PermissionConstant.get_all()


def _get_manager_permissions() -> list:
    """
    获取经理角色的权限列表。

    经理拥有所有业务模块的完整操作权限（创建、读取、更新、删除、审批），
    但不包含系统管理权限（人员、角色、权限配置、系统配置、审计日志、备份恢复）。

    Returns:
        list[str]: 权限名称列表
    """
    # 系统管理权限 - 经理不包含
    exclude_prefixes = {
        PermissionConstant.PREFIX_PERMISSION,
        PermissionConstant.PREFIX_ROLE,
        PermissionConstant.PREFIX_PERMISSION,
        PermissionConstant.PREFIX_SYSTEM_CONFIG,
        PermissionConstant.PREFIX_AUDIT_LOG,
        PermissionConstant.PREFIX_BACKUP,
    }

    result = []
    for p in PermissionConstant.get_all():
        prefix = p.split(":")[0] if ":" in p else p
        # 审计日志特殊处理
        if prefix.startswith("report_"):
            # 报表权限保留
            result.append(p)
            continue
        if prefix not in exclude_prefixes:
            result.append(p)
    return result


def _get_operator_permissions() -> list:
    """
    获取操作员角色的权限列表。

    操作员拥有业务模块的基本操作权限（创建、读取、更新），
    不包含删除、审批、导入导出等敏感操作，也不包含系统管理权限。

    Returns:
        list[str]: 权限名称列表
    """
    # 操作员排除的操作类型
    exclude_actions = {"delete", "approve", "cancel", "import", "export"}
    # 操作员排除的资源前缀
    exclude_prefixes = {
        PermissionConstant.PREFIX_PERSONNEL,
        PermissionConstant.PREFIX_ROLE,
        PermissionConstant.PREFIX_PERMISSION,
        PermissionConstant.PREFIX_SYSTEM_CONFIG,
        PermissionConstant.PREFIX_AUDIT_LOG,
        PermissionConstant.PREFIX_BACKUP,
    }

    result = []
    for p in PermissionConstant.get_all():
        prefix = p.split(":")[0] if ":" in p else p
        action = p.split(":")[1] if ":" in p else ""

        # 排除指定资源前缀
        if prefix in exclude_prefixes:
            continue

        # 报表只保留查看
        if prefix.startswith("report_") or prefix.startswith("dashboard"):
            if action == "view":
                result.append(p)
            continue

        # 排除敏感操作
        if action in exclude_actions:
            continue

        result.append(p)
    return result


def _get_viewer_permissions() -> list:
    """
    获取访客角色的权限列表。

    访客只有最基本的读取和查看权限，没有任何写入、修改或删除权限。

    Returns:
        list[str]: 权限名称列表
    """
    read_actions = {"read", "view"}
    read_prefixes = {
        PermissionConstant.PREFIX_TODO
    }

    result = []
    for p in PermissionConstant.get_all():
        prefix = p.split(":")[0] if ":" in p else p
        action = p.split(":")[1] if ":" in p else ""

        # 只读取指定资源的 read/view 权限
        if prefix in read_prefixes and action in read_actions:
            result.append(p)
    return result


# 角色-权限映射表
ROLE_PERMISSION_MAP = {
    ROLE_ADMIN: _get_admin_permissions,
    ROLE_MANAGER: _get_manager_permissions,
    ROLE_OPERATOR: _get_operator_permissions,
    ROLE_VIEWER: _get_viewer_permissions,
}

ROLE_DESCRIPTION_MAP = {
    ROLE_ADMIN: "超级管理员，拥有系统所有权限",
    ROLE_MANAGER: "业务经理，拥有所有业务模块的完整操作权限",
    ROLE_OPERATOR: "操作员，拥有业务模块的基本操作权限",
    ROLE_VIEWER: "访客，仅有只读访问权限",
}


async def init_default_roles(session):
    """
    初始化默认角色及权限关联

    创建系统预定义的四个默认角色（admin、manager、operator、viewer），
    并为每个角色分配对应的权限集。如果角色已存在则跳过创建，但会补充缺失的权限关联。

    Args:
        session: 数据库会话对象

    Returns:
        None
    """
    for role_name, get_permissions_fn in ROLE_PERMISSION_MAP.items():
        # 检查角色是否已存在（主动加载 permissions 关系，避免异步懒加载问题）
        result = await session.execute(
            select(Role)
            .where(Role.name == role_name)
            .options(selectinload(Role.permissions))  # type: ignore[arg-type]
        )
        existing_role = result.scalar_one_or_none()

        if existing_role:
            logger.info(f"角色已存在: {role_name}")
            role = existing_role
        else:
            # 创建角色
            description = ROLE_DESCRIPTION_MAP.get(role_name, "")
            role = await RoleService.create_role(
                session, role_name, description=description
            )
            # 创建后重新查询以加载 permissions 关系
            result = await session.execute(
                select(Role)
                .where(Role.name == role_name)
                .options(selectinload(Role.permissions))  # type: ignore[arg-type]
            )
            role = result.scalar_one_or_none()
            logger.info(f"创建角色: {role_name}")

        # 获取该角色应有的权限名称列表
        expected_permission_names = get_permissions_fn()

        # 获取角色当前已关联的权限名称集合
        existing_permission_names = {
            p.name for p in role.permissions
        } if role else set()

        # 分配缺失的权限
        for perm_name in expected_permission_names:
            if perm_name in existing_permission_names:
                continue

            permission = await PermissionService.get_permission_by_name(
                session, perm_name
            )
            if permission is None:
                logger.warning(f"权限不存在，跳过: {perm_name}")
                continue

            if role.id is not None and permission.id is not None:
                await PermissionService.assign_permission_to_role(
                    session, role.id, permission.id
                )
                logger.debug(f"为角色 '{role_name}' 分配权限: {perm_name}")

    # 将 admin 角色分配给超级管理员用户（主动加载 roles 关系）
    result = await session.execute(
        select(User).where(User.email == "admin@qq.com").options(selectinload(User.roles))  # type: ignore[arg-type]
    )
    admin_user = result.scalar_one_or_none()

    admin_role = await RoleService.get_role_by_name(session, ROLE_ADMIN)
    if admin_user and admin_role and admin_role.id is not None:
        # 检查是否已关联
        already_assigned = any(
            r.id == admin_role.id for r in admin_user.roles
        )
        if not already_assigned:
            await RoleService.assign_role_to_user(
                session, admin_user.id, admin_role.id
            )
            logger.info("为 admin 用户分配 admin 角色")


async def init_db():
    """
    执行数据库初始化流程

    协调执行所有数据库初始化任务，包括管理员账户创建、权限数据初始化和默认角色初始化。
    该函数是系统启动时数据库初始化的入口点。

    Returns:
        None

    Note:
        - 通过任务服务获取异步会话工厂
        - 如果会话工厂未初始化，则直接返回不执行任何操作
        - 按顺序执行：先初始化权限，再初始化角色，最后初始化管理员
        - 使用异步上下文管理器确保会话正确关闭
    """
    task_service = get_task_service_instance()
    if task_service.async_session_maker is None:
        return
    async with task_service.async_session_maker() as session:
        # 先初始化权限数据（角色依赖权限存在）
        await init_permission(session)
        # 再初始化默认角色及权限关联
        await init_default_roles(session)
        # 最后初始化管理员用户
        await dev_init_admin(session)
