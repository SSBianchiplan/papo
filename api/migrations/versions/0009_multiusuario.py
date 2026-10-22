"""multiusuário: master e estatísticas por conta

Revision ID: 0009
Revises: 0008
"""
from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"
SQL = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL / "0009_up.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute((SQL / "0009_down.sql").read_text(encoding="utf-8"))
