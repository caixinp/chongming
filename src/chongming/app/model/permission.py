from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from .relationship_table import RolePermission

if TYPE_CHECKING:
    from .role import Role


# ---------- 权限表 ----------
class Permission(SQLModel, table=True):
    """权限项，如 user:create, order:delete"""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)  # 权限标识符
    description: Optional[str] = None
    resource: str = Field(index=True)  # 资源，如 user, order, product
    action: str  # 操作，如 create, read, update, delete

    # 多对多关联
    roles: List["Role"] = Relationship(
        back_populates="permissions", link_model=RolePermission
    )
