from uuid import UUID
from sqlmodel import SQLModel, Field


# ---------- 关联表 ----------
class UserRole(SQLModel, table=True):
    """用户角色关联表"""

    user_id: UUID = Field(foreign_key="user.id", primary_key=True)
    role_id: int = Field(foreign_key="role.id", primary_key=True)


class RolePermission(SQLModel, table=True):
    """角色权限关联表"""

    role_id: int = Field(foreign_key="role.id", primary_key=True)
    permission_id: int = Field(foreign_key="permission.id", primary_key=True)
