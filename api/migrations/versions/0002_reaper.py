"""reaper de execuções órfãs

Revision ID: 0002
Revises: 0001
"""
from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
SQL = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL / "0002_up.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute((SQL / "0002_down.sql").read_text(encoding="utf-8"))
