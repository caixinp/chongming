"""
数据库模型
==========

包含用户模型和 RBAC（基于角色的访问控制）模型。

RBAC 模型关系：
- Role ──┬── RolePermission ── Permission
         └── UserRole ──────── User
"""
from typing import Optional, List

from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, ForeignKey, UniqueConstraint, BigInteger
from sqlalchemy.dialects.postgresql import JSONB


# ── 用户模型 ──────────────────────────────────────────────────────


class User(SQLModel, table=True):
    """用户表

    ID 使用 Snowflake 算法生成全局唯一、趋势递增的 64 位整数，
    不再依赖数据库自增。创建用户时由 ``user.create`` handler
    调用 ``snowflake_generator.next_id()`` 生成。
    """
    id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=False))
    username: str = Field(unique=True, index=True)
    password_hash: str
    email: Optional[str] = None
    roles: List[str] = Field(
        default=["user"],
        sa_column=Column(JSONB),
        description="冗余角色名列表，供快速查询使用",
    )
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    created_at: Optional[float] = None

    # 关联
    user_roles: List["UserRole"] = Relationship(back_populates="user")


# ── RBAC 模型 ─────────────────────────────────────────────────────


class Role(SQLModel, table=True):
    """角色表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: Optional[str] = None
    is_system: bool = Field(
        default=False,
        description="系统角色不可删除",
    )

    # 关联
    user_roles: List["UserRole"] = Relationship(back_populates="role")
    role_permissions: List["RolePermission"] = Relationship(back_populates="role")


class Permission(SQLModel, table=True):
    """权限表

    权限名格式: ``{resource}.{action}``
    例如: ``user.create``, ``order.read``, ``report.delete``
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    resource: str = Field(description="资源名称，如 user, order, report")
    action: str = Field(description="操作名称，如 create, read, update, delete")
    description: Optional[str] = None

    # 关联
    role_permissions: List["RolePermission"] = Relationship(back_populates="permission")


class UserRole(SQLModel, table=True):
    """用户-角色 关联表"""
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("user.id", ondelete="CASCADE")))
    role_id: int = Field(sa_column=Column(ForeignKey("role.id", ondelete="CASCADE")))

    # 关联
    user: User = Relationship(back_populates="user_roles")
    role: Role = Relationship(back_populates="user_roles")


class RolePermission(SQLModel, table=True):
    """角色-权限 关联表"""
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    role_id: int = Field(sa_column=Column(ForeignKey("role.id", ondelete="CASCADE")))
    permission_id: int = Field(sa_column=Column(ForeignKey("permission.id", ondelete="CASCADE")))

    # 关联
    role: Role = Relationship(back_populates="role_permissions")
    permission: Permission = Relationship(back_populates="role_permissions")
