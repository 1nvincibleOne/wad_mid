from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..schemas import Limit, Offset, Trade

router = APIRouter(prefix="/trades", tags=["Trades"])


@router.get("", response_model=list[Trade])
def list_trades(
    instrument_id: int | None = None,
    order_id: Annotated[int | None, Query(description="Trades where this order was the buyer or the seller.")] = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    """List trades, newest first. Trades are created only by matching orders."""
    sql = "SELECT * FROM trades"
    values = []
    if order_id is not None:
        sql += " WHERE %s IN (buy_order_id, sell_order_id)"
        values.append(order_id)
    if instrument_id is not None:
        sql += (" AND" if values else " WHERE") + " instrument_id = %s"
        values.append(instrument_id)
    with db.transaction() as cursor:
        cursor.execute(sql + " ORDER BY id DESC LIMIT %s OFFSET %s", [*values, limit, offset])
        return cursor.fetchall()


@router.get("/{trade_id}", response_model=Trade, responses={404: {"description": "Not found"}})
def get_trade(trade_id: int):
    with db.transaction() as cursor:
        cursor.execute("SELECT * FROM trades WHERE id = %s", (trade_id,))
        trade = cursor.fetchone()
    if trade is None:
        raise HTTPException(404, "Trade not found")
    return trade
