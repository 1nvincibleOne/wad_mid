from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from psycopg import errors

from .. import audit, db
from ..matching import LIVE, lock_instrument
from ..schemas import Instrument, InstrumentCreate, InstrumentUpdate, Limit, Offset, OrderBook

router = APIRouter(prefix="/instruments", tags=["Instruments"])


def fetch(cursor, instrument_id):
    cursor.execute("SELECT * FROM instruments WHERE id = %s", (instrument_id,))
    instrument = cursor.fetchone()
    if instrument is None:
        raise HTTPException(404, "Instrument not found")
    return instrument


@router.get("", response_model=list[Instrument])
def list_instruments(
    is_active: bool | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    """List instruments by symbol."""
    sql, values = db.page("SELECT * FROM instruments", {"is_active": is_active}, limit, offset, "symbol")
    with db.transaction() as cursor:
        cursor.execute(sql, values)
        return cursor.fetchall()


@router.get("/{instrument_id}", response_model=Instrument, responses={404: {"description": "Not found"}})
def get_instrument(instrument_id: int):
    with db.transaction() as cursor:
        return fetch(cursor, instrument_id)


@router.post("", response_model=Instrument, status_code=201, responses={409: {"description": "Symbol exists"}})
def create_instrument(body: InstrumentCreate):
    """List a new instrument for trading."""
    try:
        with db.transaction() as cursor:
            cursor.execute(
                """INSERT INTO instruments (symbol, name, currency, tick_size)
                   VALUES (%s, %s, %s, %s) RETURNING *""",
                (body.symbol, body.name, body.currency, body.tick_size),
            )
            instrument = cursor.fetchone()
            audit.record(cursor, "instrument", instrument["id"], "created", instrument)
            return instrument
    except errors.UniqueViolation:
        raise HTTPException(409, f"Symbol {body.symbol} already exists")


@router.patch("/{instrument_id}", response_model=Instrument, responses={404: {"description": "Not found"}})
def update_instrument(instrument_id: int, body: InstrumentUpdate):
    """Rename an instrument, or halt and resume its trading."""
    changes = body.model_dump(exclude_none=True)
    with db.transaction() as cursor:
        before = lock_instrument(cursor, instrument_id)
        # Keys come from the InstrumentUpdate model, never from raw input.
        assignments = ", ".join(f"{column} = %({column})s" for column in changes)
        cursor.execute(
            f"UPDATE instruments SET {assignments} WHERE id = %(id)s RETURNING *",
            {**changes, "id": instrument_id},
        )
        instrument = cursor.fetchone()
        audit.record(cursor, "instrument", instrument_id, "updated", {
            column: {"from": before[column], "to": value} for column, value in changes.items()
        })
        return instrument


@router.delete("/{instrument_id}", status_code=204, responses={
    404: {"description": "Not found"}, 409: {"description": "Instrument has orders"},
})
def delete_instrument(instrument_id: int):
    """Delete an instrument that has never been traded. Halt traded ones instead."""
    with db.transaction() as cursor:
        instrument = lock_instrument(cursor, instrument_id)
        cursor.execute("SELECT 1 FROM orders WHERE instrument_id = %s LIMIT 1", (instrument_id,))
        if cursor.fetchone():
            raise HTTPException(409, "Instrument has order history; set is_active to false to halt it")
        cursor.execute("DELETE FROM instruments WHERE id = %s", (instrument_id,))
        audit.record(cursor, "instrument", instrument_id, "deleted", instrument)
    return Response(status_code=204)


@router.get("/{instrument_id}/book", response_model=OrderBook, responses={404: {"description": "Not found"}})
def get_order_book(instrument_id: int, depth: Annotated[int, Query(ge=1, le=100)] = 10):
    """Resting quantity at each price level, best prices first."""
    with db.transaction() as cursor:
        instrument = fetch(cursor, instrument_id)
        levels = {}
        for side, best_first in (("buy", "DESC"), ("sell", "ASC")):
            cursor.execute(
                # SUM over integer columns returns bigint: totals can pass 2^31 even though each order can't.
                f"""SELECT price, SUM(quantity - filled_quantity) AS quantity, COUNT(*) AS orders
                    FROM orders WHERE instrument_id = %s AND side = %s AND status = ANY(%s)
                    GROUP BY price ORDER BY price {best_first} LIMIT %s""",
                (instrument_id, side, LIVE, depth),
            )
            levels[side] = cursor.fetchall()
        cursor.execute(
            "SELECT price FROM trades WHERE instrument_id = %s ORDER BY id DESC LIMIT 1", (instrument_id,),
        )
        last = cursor.fetchone()

    best_bid = levels["buy"][0]["price"] if levels["buy"] else None
    best_ask = levels["sell"][0]["price"] if levels["sell"] else None
    return {
        "instrument_id": instrument_id, "symbol": instrument["symbol"],
        "bids": levels["buy"], "asks": levels["sell"],
        "best_bid": best_bid, "best_ask": best_ask,
        "spread": best_ask - best_bid if best_bid is not None and best_ask is not None else None,
        "last_price": last["price"] if last else None,
    }
