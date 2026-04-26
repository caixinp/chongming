from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from .relationship_table import RolePermission

if TYPE_CHECKING:
    from .role import Role


class Permission(SQLModel, table=True):
    """
    权限模型类，用于定义系统中的权限项。

    权限采用资源:操作的格式进行标识，例如：
    - user:create 表示创建用户的权限
    - order:delete 表示删除订单的权限

    Attributes:
        id: 权限的唯一标识符，主键，自增
        name: 权限标识符，唯一且建立索引，格式为"资源:操作"
        description: 权限的描述信息，可选字段
        resource: 资源名称，建立索引，如 user、order、product 等
        action: 操作类型，如 create、read、update、delete 等
        roles: 关联的角色列表，通过 RolePermission 中间表实现多对多关系
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: Optional[str] = None
    resource: str = Field(index=True)
    action: str

    roles: List["Role"] = Relationship(
        back_populates="permissions", link_model=RolePermission
    )
