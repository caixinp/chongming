"""
Pydantic Models - 自动生成

生成自: config.toml
指令: chongming gen-models
"""

from datetime import datetime
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field

class UserAuthInput(BaseModel):
    """USER.AUTH 请求参数模型"""
    user_id: str
    roles: list
    username: str
    email: str
    other: dict


class UserAuthOutput(BaseModel):
    """USER.AUTH 响应结果模型"""
    status: bool
    token: str
    timestamp: float = 0.0


class UserLoginInput(BaseModel):
    """USER.LOGIN 请求参数模型"""
    user_name: str
    password: str


class UserLoginOutput(BaseModel):
    """USER.LOGIN 响应结果模型"""
    status: bool
    token: str
    user_id: str
    username: str
    email: str
    other: dict
    roles: str
    timestamp: float = 0.0


class UserCreateInput(BaseModel):
    """USER.CREATE 请求参数模型"""
    username: str
    password_hash: str
    email: str
    roles: list


class UserCreateOutput(BaseModel):
    """USER.CREATE 响应结果模型"""
    id: int
    username: str
    email: str
    roles: list
    created_at: float


class UserGetInput(BaseModel):
    """USER.GET 请求参数模型"""
    user_id: int


class UserGetOutput(BaseModel):
    """USER.GET 响应结果模型"""
    id: int
    username: str
    email: str
    roles: list


class UserUpdateInput(BaseModel):
    """USER.UPDATE 请求参数模型"""
    user_id: int
    username: str
    email: str
    roles: list


class UserUpdateOutput(BaseModel):
    """USER.UPDATE 响应结果模型"""
    id: int
    username: str
    email: str
    roles: list


class UserDeleteInput(BaseModel):
    """USER.DELETE 请求参数模型"""
    user_id: int


class UserDeleteOutput(BaseModel):
    """USER.DELETE 响应结果模型"""
    status: bool
    message: str


class UserRegisterInput(BaseModel):
    """USER.REGISTER 请求参数模型"""
    username: str
    password: str
    email: str = ""


class UserRegisterOutput(BaseModel):
    """USER.REGISTER 响应结果模型"""
    status: bool
    token: str
    user_id: int
    username: str
    email: str
    roles: list
    timestamp: float = 0.0


class UserListInput(BaseModel):
    """USER.LIST 请求参数模型"""
    offset: int
    limit: int


class UserListOutput(BaseModel):
    """USER.LIST 响应结果模型"""
    users: list
    total: int
    offset: int
    limit: int


# ── 角色管理模型 ──────────────────────────────────────────────────


class RoleCreateInput(BaseModel):
    """ROLE.CREATE 请求参数模型"""
    name: str
    description: str = ""


class RoleCreateOutput(BaseModel):
    """ROLE.CREATE 响应结果模型"""
    id: int
    name: str
    description: str
    is_system: bool


class RoleGetInput(BaseModel):
    """ROLE.GET 请求参数模型"""
    role_id: int


class RoleGetOutput(BaseModel):
    """ROLE.GET 响应结果模型"""
    id: int
    name: str
    description: str
    is_system: bool
    permissions: List[str]


class RoleUpdateInput(BaseModel):
    """ROLE.UPDATE 请求参数模型"""
    role_id: int
    name: str = ""
    description: str = ""


class RoleUpdateOutput(BaseModel):
    """ROLE.UPDATE 响应结果模型"""
    id: int
    name: str
    description: str
    is_system: bool


class RoleDeleteInput(BaseModel):
    """ROLE.DELETE 请求参数模型"""
    role_id: int


class RoleDeleteOutput(BaseModel):
    """ROLE.DELETE 响应结果模型"""
    status: bool
    message: str


class RoleListInput(BaseModel):
    """ROLE.LIST 请求参数模型"""
    offset: int = 0
    limit: int = 20


class RoleListOutput(BaseModel):
    """ROLE.LIST 响应结果模型"""
    roles: list
    total: int


class RoleAssignPermissionInput(BaseModel):
    """ROLE.ASSIGN_PERMISSION 请求参数模型"""
    role_id: int
    permission_name: str


class RoleAssignPermissionOutput(BaseModel):
    """ROLE.ASSIGN_PERMISSION 响应结果模型"""
    status: bool
    message: str


class RoleRevokePermissionInput(BaseModel):
    """ROLE.REVOKE_PERMISSION 请求参数模型"""
    role_id: int
    permission_name: str


class RoleRevokePermissionOutput(BaseModel):
    """ROLE.REVOKE_PERMISSION 响应结果模型"""
    status: bool
    message: str


# ── 权限管理模型 ──────────────────────────────────────────────────


class PermissionCreateInput(BaseModel):
    """PERMISSION.CREATE 请求参数模型"""
    name: str
    resource: str
    action: str
    description: str = ""


class PermissionCreateOutput(BaseModel):
    """PERMISSION.CREATE 响应结果模型"""
    id: int
    name: str
    resource: str
    action: str
    description: str


class PermissionListInput(BaseModel):
    """PERMISSION.LIST 请求参数模型"""
    offset: int = 0
    limit: int = 50
    resource: str = ""


class PermissionListOutput(BaseModel):
    """PERMISSION.LIST 响应结果模型"""
    permissions: list
    total: int


class PermissionDeleteInput(BaseModel):
    """PERMISSION.DELETE 请求参数模型"""
    permission_id: int


class PermissionDeleteOutput(BaseModel):
    """PERMISSION.DELETE 响应结果模型"""
    status: bool
    message: str


# ── 用户角色分配模型 ──────────────────────────────────────────────


class UserRoleAssignInput(BaseModel):
    """USERROLE.ASSIGN 请求参数模型"""
    user_id: int
    role_name: str


class UserRoleAssignOutput(BaseModel):
    """USERROLE.ASSIGN 响应结果模型"""
    status: bool
    message: str


class UserRoleRevokeInput(BaseModel):
    """USERROLE.REVOKE 请求参数模型"""
    user_id: int
    role_name: str


class UserRoleRevokeOutput(BaseModel):
    """USERROLE.REVOKE 响应结果模型"""
    status: bool
    message: str


class UserRoleListInput(BaseModel):
    """USERROLE.LIST 请求参数模型"""
    user_id: int


class UserRoleListOutput(BaseModel):
    """USERROLE.LIST 响应结果模型"""
    user_id: int
    username: str
    roles: list
    permissions: List[str]
