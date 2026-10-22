"""escolha de modelo por nível e catálogo

Revision ID: 0004
Revises: 0003
"""
from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"
SQL = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL / "0004_up.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute((SQL / "0004_down.sql").read_text(encoding="utf-8"))
