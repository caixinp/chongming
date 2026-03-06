from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...model.todo import TodoCreate, TodoUpdate, TodoRead
from ...core.database import get_session
from ...service.todo import TodoService
from ...model.user import User
from ..deps import get_current_user


router = APIRouter()


# -------------------- 路由 --------------------
@router.post("/", response_model=TodoRead, dependencies=[Depends(get_current_user)])
async def create_todo(
    todo: TodoCreate,
    session: AsyncSession = Depends(get_session),
):
    return await TodoService.create_todo(todo, session)


@router.get(
    "/", response_model=List[TodoRead], dependencies=[Depends(get_current_user)]
)
async def read_todos(
    offset: int = 0, limit: int = 100, session: AsyncSession = Depends(get_session)
):
    return await TodoService.get_todos(offset, limit, session)


@router.get(
    "/{todo_id}", response_model=TodoRead, dependencies=[Depends(get_current_user)]
)
async def read_todo(todo_id: int, session: AsyncSession = Depends(get_session)):
    todo = await TodoService.get_todo_by_id(todo_id, session)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.patch(
    "/{todo_id}", response_model=TodoRead, dependencies=[Depends(get_current_user)]
)
async def update_todo(
    todo_id: int, todo_update: TodoUpdate, session: AsyncSession = Depends(get_session)
):
    todo = await TodoService.update_todo(todo_id, todo_update, session)
    return todo


@router.delete("/{todo_id}", dependencies=[Depends(get_current_user)])
async def delete_todo(todo_id: int, session: AsyncSession = Depends(get_session)):
    is_deleted = await TodoService.delete_todo(todo_id, session)
    if not is_deleted:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"ok": True}
