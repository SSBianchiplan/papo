"""skills

Revision ID: 0006
Revises: 0005
"""
from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
SQL = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL / "0006_up.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute((SQL / "0006_down.sql").read_text(encoding="utf-8"))
