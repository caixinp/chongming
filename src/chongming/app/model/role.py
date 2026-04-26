from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship
from pydantic import BaseModel

from .relationship_table import UserRole, RolePermission

if TYPE_CHECKING:
    from .user import User
    from .permission import Permission


# ---------- 角色表 ----------
class Role(SQLModel, table=True):
    """
    角色模型类，用于定义系统中的用户角色。

    该类继承自SQLModel，映射到数据库中的角色表。每个角色可以有多个用户和多个权限，
    通过中间表UserRole和RolePermission实现多对多关系。

    Attributes:
        id: 角色的唯一标识符，主键，自增
        name: 角色名称，具有唯一性约束和索引，例如：admin, manager, operator, viewer
        description: 角色的描述信息，可选字段
        is_only_user: 标识该角色是否仅限单个用户使用，默认为False
        users: 与该角色关联的用户列表，通过UserRole中间表建立多对多关系
        permissions: 与该角色关联的权限列表，通过RolePermission中间表建立多对多关系
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)  # admin, manager, operator, viewer
    description: Optional[str] = None
    is_only_user: bool = Field(default=False)
    users: List["User"] = Relationship(back_populates="roles", link_model=UserRole)
    permissions: List["Permission"] = Relationship(
        back_populates="roles", link_model=RolePermission
    )


class RoleUpdate(BaseModel):
    """
    角色更新请求模型类，用于接收角色更新时的参数。

    该类继承自Pydantic的BaseModel，所有字段均为可选，允许部分更新角色信息。

    Attributes:
        name: 更新后的角色名称，可选字段
        description: 更新后的角色描述信息，可选字段
    """

    name: Optional[str] = None
    description: Optional[str] = None
