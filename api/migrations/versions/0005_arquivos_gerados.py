"""arquivos gerados pelo agente

Revision ID: 0005
Revises: 0004
"""
from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
SQL = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL / "0005_up.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute((SQL / "0005_down.sql").read_text(encoding="utf-8"))
