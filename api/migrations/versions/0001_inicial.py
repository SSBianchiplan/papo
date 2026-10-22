"""schema inicial: usuários, agentes, conversas, documentos, execuções e trilha

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
SQL = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL / "0001_up.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute((SQL / "0001_down.sql").read_text(encoding="utf-8"))
