from typing import Sequence, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..model.todo import TodoCreate, Todo, TodoUpdate


class TodoService:
    @staticmethod
    async def create_todo(todo: TodoCreate, session: AsyncSession) -> Todo:
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
        result = await session.execute(select(Todo).offset(offset).limit(limit))
        todos = result.scalars().all()
        return todos

    @staticmethod
    async def get_todo_by_id(
        todo_id: int,
        session: AsyncSession,
    ) -> Optional[Todo]:
        todo = await session.get(Todo, todo_id)
        return todo

    @staticmethod
    async def update_todo(
        todo_id: int,
        todo_update: TodoUpdate,
        session: AsyncSession,
    ) -> Optional[Todo]:
        todo = await session.get(Todo, todo_id)
        if not todo:
            return None
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
        todo = await session.get(Todo, todo_id)
        if not todo:
            return False
        await session.delete(todo)
        await session.commit()
        return True
