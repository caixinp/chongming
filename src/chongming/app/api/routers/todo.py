from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...model.todo import TodoCreate, TodoUpdate, TodoRead
from ...core.database import get_session
from ...service.todo import TodoService
from ..deps import get_current_user


router = APIRouter(dependencies=[Depends(get_current_user)])


# -------------------- 路由 --------------------
@router.post("/", response_model=TodoRead)
async def create_todo(
    todo: TodoCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    创建新的待办事项

    Args:
        todo: 待办事项创建请求体，包含待办事项的详细信息
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        TodoRead: 创建成功的待办事项对象，包含完整的待办事项信息
    """
    return await TodoService.create_todo(todo, session)


@router.get("/", response_model=List[TodoRead])
async def read_todos(
    offset: int = 0, limit: int = 100, session: AsyncSession = Depends(get_session)
):
    """
    获取待办事项列表

    Args:
        offset: 分页偏移量，默认为0，用于指定从第几条记录开始查询
        limit: 每页返回的最大记录数，默认为100，用于限制返回结果的数量
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        List[TodoRead]: 待办事项列表，包含指定范围内的所有待办事项
    """
    return await TodoService.get_todos(offset, limit, session)


@router.get("/{todo_id}", response_model=TodoRead)
async def read_todo(todo_id: int, session: AsyncSession = Depends(get_session)):
    """
    根据ID获取单个待办事项

    Args:
        todo_id: 待办事项的唯一标识符
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        TodoRead: 查询到的待办事项对象

    Raises:
        HTTPException: 当待办事项不存在时抛出404错误
    """
    todo = await TodoService.get_todo_by_id(todo_id, session)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.patch("/{todo_id}", response_model=TodoRead)
async def update_todo(
    todo_id: int, todo_update: TodoUpdate, session: AsyncSession = Depends(get_session)
):
    """
    更新待办事项信息

    Args:
        todo_id: 待办事项的唯一标识符
        todo_update: 待办事项更新请求体，包含需要更新的字段信息
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        TodoRead: 更新后的待办事项对象，包含最新的待办事项信息
    """
    todo = await TodoService.update_todo(todo_id, todo_update, session)
    return todo


@router.delete("/{todo_id}")
async def delete_todo(todo_id: int, session: AsyncSession = Depends(get_session)):
    """
    删除待办事项

    Args:
        todo_id: 待办事项的唯一标识符
        session: 数据库会话对象，用于执行数据库操作

    Returns:
        dict: 包含操作结果的字典，{"ok": True} 表示删除成功

    Raises:
        HTTPException: 当待办事项不存在时抛出404错误
    """
    is_deleted = await TodoService.delete_todo(todo_id, session)
    if not is_deleted:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"ok": True}
