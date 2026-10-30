import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).parent


def connect():
    return psycopg.connect(
        host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], connect_timeout=5,
        options="-c timezone=UTC", row_factory=dict_row,
    )


@contextmanager
def transaction():
    """Yield a cursor. Commits when the block ends, rolls back if it raises."""
    with connect() as connection, connection.cursor() as cursor:
        yield cursor


def initialize():
    with connect() as connection:
        connection.execute((HERE / "schema.sql").read_text(encoding="utf-8"))
        if os.environ.get("SEED_DEMO_DATA", "false").lower() == "true":
            connection.execute((HERE / "seed.sql").read_text(encoding="utf-8"))


def page(sql, filters, limit, offset, order_by):
    """Append optional equality filters, ordering and pagination to a SELECT."""
    clauses, values = [], []
    for column, value in filters.items():
        if value is not None:
            clauses.append(f"{column} = %s")  # column names are fixed in code
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return f"{sql}{where} ORDER BY {order_by} LIMIT %s OFFSET %s", [*values, limit, offset]
