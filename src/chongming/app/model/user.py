from typing import Optional, List, Dict, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship
from pydantic import BaseModel

from .relationship_table import UserRole
from uuid import uuid4, UUID

if TYPE_CHECKING:
    from .role import Role


class UserBase(SQLModel):
    """
    用户基础模型

    定义用户的核心属性，作为其他用户相关模型的基类。
    包含用户的基本信息和状态标识。

    Attributes:
        email: 用户邮箱地址，唯一且建立索引
        username: 用户名，可选，最大长度50字符
        full_name: 用户全名，可选，最大长度100字符
        is_active: 用户激活状态，默认为True
        is_superuser: 是否为超级管理员，默认为False
        created_at: 创建时间，可选字段
    """

    email: str = Field(unique=True, index=True)
    username: Optional[str] = Field(default=None, max_length=50)
    full_name: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    created_at: Optional[str] = Field(default=None)


class User(UserBase, table=True):
    """
    用户数据库模型

    继承自UserBase，用于数据库表映射。
    包含用户的完整信息以及与角色的多对多关系。

    Attributes:
        id: 用户唯一标识符，UUID类型，自动生成
        hashed_password: 加密后的密码
        roles: 用户关联的角色列表，通过UserRole中间表实现多对多关系
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    hashed_password: str
    roles: List["Role"] = Relationship(back_populates="users", link_model=UserRole)


class UserCreate(UserBase):
    """
    用户创建请求模型

    用于创建新用户时的数据验证和传输。
    在UserBase基础上增加了密码字段。

    Attributes:
        password: 用户明文密码，用于创建时传入
    """

    password: str


class UserRead(UserBase):
    """
    用户读取响应模型

    用于向客户端返回用户信息。
    在UserBase基础上增加了用户ID字段。

    Attributes:
        id: 用户唯一标识符，UUID类型
    """

    id: UUID


class UserLogin(BaseModel):
    """
    用户登录请求模型

    用于处理用户登录时的数据验证。

    Attributes:
        email: 用户邮箱地址
        password: 用户密码
    """

    email: str
    password: str


class Userlogout(BaseModel):
    """
    用户登出响应模型

    用于返回登出操作的结果。

    Attributes:
        code: 响应状态码，默认为200表示成功
        message: 响应消息，默认为"logout success"
    """

    code: int = 200
    message: str = "logout success"


class UserSession(BaseModel):
    """
    用户会话信息模型

    用于存储和返回用户的会话相关信息。

    Attributes:
        user_id: 用户唯一标识符
        sessions: 会话列表，每个会话为字典类型，键值均为字符串或None
        count: 会话总数
    """

    user_id: str
    sessions: List[Dict[str, Optional[str]]]
    count: int
