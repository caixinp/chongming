from typing import Optional

from sqlmodel import SQLModel, Field


# 定义模型
class TodoBase(SQLModel):
    title: str
    description: Optional[str] = None
    completed: bool = False


class Todo(TodoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class TodoCreate(TodoBase):
    pass


class TodoRead(TodoBase):
    id: int


class TodoUpdate(SQLModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None
