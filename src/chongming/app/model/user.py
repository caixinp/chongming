from typing import Optional, List, Dict, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship
from pydantic import BaseModel

from .relationship_table import UserRole
from uuid import uuid4, UUID

if TYPE_CHECKING:
    from .role import Role


class UserBase(SQLModel):
    email: str = Field(unique=True, index=True)
    username: Optional[str] = Field(default=None, max_length=50)
    full_name: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    created_at: Optional[str] = Field(default=None)  # 可自动填充，此处略


class User(UserBase, table=True):
    """用户模型"""

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    hashed_password: str
    roles: List["Role"] = Relationship(back_populates="users", link_model=UserRole)


class UserCreate(UserBase):
    """用户创建模型"""

    password: str


class UserRead(UserBase):
    """用户读取模型"""

    id: UUID


class UserLogin(BaseModel):
    email: str
    password: str


class Userlogout(BaseModel):
    code: int = 200
    message: str = "logout success"


class UserSession(BaseModel):
    user_id: str
    sessions: List[Dict[str, Optional[str]]]
    count: int
