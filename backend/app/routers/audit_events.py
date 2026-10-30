from fastapi import APIRouter

from .. import db
from ..schemas import AuditAction, AuditEvent, EntityType, Limit, Offset

router = APIRouter(prefix="/audit-events", tags=["Audit"])


@router.get("", response_model=list[AuditEvent])
def list_audit_events(
    entity_type: EntityType | None = None,
    entity_id: int | None = None,
    action: AuditAction | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    """Read the append-only trail of every change, newest first.

    For the full history of one order, filter by entity_type=order and its entity_id.
    """
    filters = {"entity_type": entity_type, "entity_id": entity_id, "action": action}
    sql, values = db.page("SELECT * FROM audit_events", filters, limit, offset, "id DESC")
    with db.transaction() as cursor:
        cursor.execute(sql, values)
        return cursor.fetchall()
