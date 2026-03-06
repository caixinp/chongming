from typing import Optional
from sqlmodel import SQLModel, Field
from pydantic import BaseModel


class UserBase(SQLModel):
    email: str = Field(unique=True, index=True)
    username: Optional[str] = Field(default=None, max_length=50)
    full_name: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    created_at: Optional[str] = Field(default=None)  # 可自动填充，此处略


class User(UserBase, table=True):
    """用户模型"""

    id: Optional[int] = Field(default=None, primary_key=True)
    hashed_password: str


class UserCreate(UserBase):
    """用户创建模型"""

    password: str


class UserRead(UserBase):
    """用户读取模型"""

    id: int


class UserLogin(BaseModel):
    email: str
    password: str
