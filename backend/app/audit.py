import json
from functools import partial

from psycopg.types.json import Jsonb

# Decimals and timestamps become strings, so prices stay exact in the trail.
dumps = partial(json.dumps, default=str)


def record(cursor, entity_type, entity_id, action, data):
    """Append one event in the caller's transaction: it commits or rolls back with the change."""
    cursor.execute(
        "INSERT INTO audit_events (entity_type, entity_id, action, data) VALUES (%s, %s, %s, %s)",
        (entity_type, entity_id, action, Jsonb(data, dumps=dumps)),
    )
