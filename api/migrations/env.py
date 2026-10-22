"""Alembic: migrations em SQL puro, executadas pelo papel dono.

Usa driver síncrono (psycopg) porque o protocolo simples aceita múltiplos comandos por execução.
"""
import os

from alembic import context
from sqlalchemy import create_engine, pool

URL = os.environ["MIGRATION_DATABASE_URL"].replace("+asyncpg", "+psycopg")

engine = create_engine(URL, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
