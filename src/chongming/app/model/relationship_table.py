from uuid import UUID
from sqlmodel import SQLModel, Field


# ---------- 关联表 ----------
class UserRole(SQLModel, table=True):
    """
    用户角色关联表

    用于实现用户与角色之间的多对多关系。
    每个记录表示一个用户拥有的一个角色。

    Attributes:
        user_id: 用户ID，外键关联到user表的id字段，作为复合主键的一部分
        role_id: 角色ID，外键关联到role表的id字段，作为复合主键的一部分
    """

    user_id: UUID = Field(foreign_key="user.id", primary_key=True)
    role_id: int = Field(foreign_key="role.id", primary_key=True)


class RolePermission(SQLModel, table=True):
    """
    角色权限关联表

    用于实现角色与权限之间的多对多关系。
    每个记录表示一个角色拥有的一项权限。

    Attributes:
        role_id: 角色ID，外键关联到role表的id字段，作为复合主键的一部分
        permission_id: 权限ID，外键关联到permission表的id字段，作为复合主键的一部分
    """

    role_id: int = Field(foreign_key="role.id", primary_key=True)
    permission_id: int = Field(foreign_key="permission.id", primary_key=True)
