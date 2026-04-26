from typing import Optional

from sqlmodel import SQLModel, Field


# 定义模型
class TodoBase(SQLModel):
    """
    Todo任务的基础模型类，包含任务的通用字段。

    Attributes:
        title: 任务标题，必填字段
        description: 任务描述，可选字段，默认为None
        completed: 任务完成状态，布尔值，默认为False
    """

    title: str
    description: Optional[str] = None
    completed: bool = False


class Todo(TodoBase, table=True):
    """
    Todo任务的数据库表模型类，继承自TodoBase。

    该类对应数据库中的todo表，用于存储和查询任务数据。

    Attributes:
        id: 任务唯一标识符，主键，由数据库自动生成
    """

    id: Optional[int] = Field(default=None, primary_key=True)


class TodoCreate(TodoBase):
    """
    创建Todo任务时使用的请求模型类。

    继承自TodoBase，用于接收前端传入的新建任务数据。
    不包含id字段，因为id由数据库自动生成。
    """

    pass


class TodoRead(TodoBase):
    """
    读取Todo任务时使用的响应模型类。

    继承自TodoBase，用于向客户端返回任务数据。
    包含完整的任务信息，包括自动生成的id字段。

    Attributes:
        id: 任务唯一标识符，整数类型，必填字段
    """

    id: int


class TodoUpdate(SQLModel):
    """
    更新Todo任务时使用的请求模型类。

    所有字段均为可选，允许部分更新任务信息。
    只有提供的字段会被更新，未提供的字段保持原值。

    Attributes:
        title: 任务标题，可选字段
        description: 任务描述，可选字段
        completed: 任务完成状态，可选字段
    """

    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None
