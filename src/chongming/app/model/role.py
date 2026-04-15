from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from .relationship_table import UserRole, RolePermission

if TYPE_CHECKING:
    from .user import User
    from .permission import Permission


# ---------- 角色表 ----------
class Role(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)  # admin, manager, operator, viewer
    description: Optional[str] = None
    is_only_user: bool = Field(default=False)
    users: List["User"] = Relationship(back_populates="roles", link_model=UserRole)
    permissions: List["Permission"] = Relationship(
        back_populates="roles", link_model=RolePermission
    )
