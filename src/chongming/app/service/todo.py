from typing import Sequence, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..model.todo import TodoCreate, Todo, TodoUpdate


class TodoService:
    """待办事项服务类，提供待办事项的增删改查操作"""

    @staticmethod
    async def create_todo(todo: TodoCreate, session: AsyncSession) -> Todo:
        """
        创建新的待办事项

        Args:
            todo: 待办事项创建数据对象，包含待办事项的初始信息
            session: 异步数据库会话对象，用于执行数据库操作

        Returns:
            Todo: 创建成功后的待办事项对象，包含生成的ID等信息
        """
        db_todo = Todo.model_validate(todo)
        session.add(db_todo)
        await session.commit()
        await session.refresh(db_todo)
        return db_todo

    @staticmethod
    async def get_todos(
        offset: int,
        limit: int,
        session: AsyncSession,
    ) -> Sequence[Todo]:
        """
        获取待办事项列表（支持分页）

        Args:
            offset: 查询偏移量，指定从第几条记录开始查询
            limit: 查询限制数量，指定最多返回多少条记录
            session: 异步数据库会话对象，用于执行数据库操作

        Returns:
            Sequence[Todo]: 待办事项对象列表，按查询条件返回的结果集
        """
        result = await session.execute(select(Todo).offset(offset).limit(limit))
        todos = result.scalars().all()
        return todos

    @staticmethod
    async def get_todo_by_id(
        todo_id: int,
        session: AsyncSession,
    ) -> Optional[Todo]:
        """
        根据ID获取单个待办事项

        Args:
            todo_id: 待办事项的唯一标识ID
            session: 异步数据库会话对象，用于执行数据库操作

        Returns:
            Optional[Todo]: 如果找到则返回待办事项对象，否则返回None
        """
        todo = await session.get(Todo, todo_id)
        return todo

    @staticmethod
    async def update_todo(
        todo_id: int,
        todo_update: TodoUpdate,
        session: AsyncSession,
    ) -> Optional[Todo]:
        """
        更新待办事项信息

        Args:
            todo_id: 待办事项的唯一标识ID
            todo_update: 待办事项更新数据对象，包含需要更新的字段信息
            session: 异步数据库会话对象，用于执行数据库操作

        Returns:
            Optional[Todo]: 如果更新成功则返回更新后的待办事项对象，如果待办事项不存在则返回None
        """
        todo = await session.get(Todo, todo_id)
        if not todo:
            return None

        # 提取需要更新的字段数据，排除未设置的字段
        update_data = todo_update.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(todo, key, value)

        session.add(todo)
        await session.commit()
        await session.refresh(todo)
        return todo

    @staticmethod
    async def delete_todo(
        todo_id: int,
        session: AsyncSession,
    ) -> bool:
        """
        删除待办事项

        Args:
            todo_id: 待办事项的唯一标识ID
            session: 异步数据库会话对象，用于执行数据库操作

        Returns:
            bool: 如果删除成功返回True，如果待办事项不存在返回False
        """
        todo = await session.get(Todo, todo_id)
        if not todo:
            return False
        await session.delete(todo)
        await session.commit()
        return True
