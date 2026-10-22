"""governança de IA (modelo de camadas, ficha dos agentes) e Consultor de IA

Revision ID: 0008
Revises: 0007
"""
import json
from pathlib import Path

import yaml
from alembic import op

revision = "0008"
down_revision = "0007"
SQL = Path(__file__).resolve().parent.parent / "sql"
RUBRICA = Path(__file__).resolve().parents[2] / "app" / "consultor" / "rubrica" / "v1.0.0.yaml"


def upgrade() -> None:
    op.execute((SQL / "0008_up.sql").read_text(encoding="utf-8"))
    definicao = yaml.safe_load(RUBRICA.read_text(encoding="utf-8"))
    payload = json.dumps(definicao, ensure_ascii=False).replace("'", "''")
    op.execute(f"INSERT INTO rubrica_versao (versao, definicao, ativa, nota) VALUES ('1.0.0', '{payload}'::jsonb, true, "
               "'Rubrica inicial da SPEC-GPS-PAPO-CIA-001')")


def downgrade() -> None:
    op.execute((SQL / "0008_down.sql").read_text(encoding="utf-8"))
