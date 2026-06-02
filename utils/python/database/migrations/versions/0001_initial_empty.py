"""initial empty baseline

Revision ID: 0001
Revises: 
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """标记当前数据库状态为基线"""
    pass


def downgrade() -> None:
    """回滚到此基线"""
    pass
