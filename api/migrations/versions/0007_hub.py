"""docs do hub

Revision ID: 0007
Revises: 0006
"""
from pathlib import Path

from alembic import op

revision = "0007"
down_revision = "0006"
SQL = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL / "0007_up.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute((SQL / "0007_down.sql").read_text(encoding="utf-8"))
