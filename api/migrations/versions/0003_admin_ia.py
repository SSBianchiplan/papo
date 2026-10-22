"""administração da IA: chave, orçamento e preços

Revision ID: 0003
Revises: 0002
"""
from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
SQL = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL / "0003_up.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute((SQL / "0003_down.sql").read_text(encoding="utf-8"))
