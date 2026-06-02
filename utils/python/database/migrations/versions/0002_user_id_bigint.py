"""make all id columns bigint for Snowflake ID support

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02 02:44:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002"
down_revision: str = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将用户表 user.id 从 INTEGER 改为 BIGINT（Snowflake ID）"""
    op.alter_column("user", "id",
        existing_type=sa.INTEGER(),
        type_=sa.BIGINT(),
        existing_nullable=False,
        postgresql_using="id::bigint",
    )


def downgrade() -> None:
    """将 user.id 从 BIGINT 改回 INTEGER"""
    op.alter_column("user", "id",
        existing_type=sa.BIGINT(),
        type_=sa.INTEGER(),
        existing_nullable=False,
        postgresql_using="id::integer",
    )
