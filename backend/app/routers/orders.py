from fastapi import APIRouter, HTTPException

from .. import audit, db
from ..matching import LIVE, lock_instrument, match, require_active, require_tick
from ..schemas import (
    Limit, Offset, Order, OrderCreate, OrderExecution, OrderStatus, OrderUpdate, Side, Trader,
)

router = APIRouter(prefix="/orders", tags=["Orders"])

NOT_FOUND = {404: {"description": "Not found"}}


def fetch(cursor, order_id):
    cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


def lock_live_order(cursor, order_id):
    """Lock the order's instrument, then re-read the order so its state is current."""
    instrument = lock_instrument(cursor, fetch(cursor, order_id)["instrument_id"])
    order = fetch(cursor, order_id)
    if order["status"] not in LIVE:
        raise HTTPException(409, f"Order is {order['status']}")
    return instrument, order


@router.get("", response_model=list[Order])
def list_orders(
    instrument_id: int | None = None,
    trader: Trader | None = None,
    side: Side | None = None,
    status: OrderStatus | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    """List orders, newest first."""
    filters = {"instrument_id": instrument_id, "trader": trader, "side": side, "status": status}
    sql, values = db.page("SELECT * FROM orders", filters, limit, offset, "id DESC")
    with db.transaction() as cursor:
        cursor.execute(sql, values)
        return cursor.fetchall()


@router.get("/{order_id}", response_model=Order, responses=NOT_FOUND)
def get_order(order_id: int):
    with db.transaction() as cursor:
        return fetch(cursor, order_id)


@router.post("", response_model=OrderExecution, status_code=201, responses={
    404: {"description": "Instrument not found"}, 409: {"description": "Trading halted"},
})
def place_order(body: OrderCreate):
    """Place a limit order. It trades immediately against crossing orders; the rest joins the book."""
    with db.transaction() as cursor:
        instrument = lock_instrument(cursor, body.instrument_id)
        require_active(instrument)
        require_tick(body.price, instrument)
        cursor.execute(
            """INSERT INTO orders (instrument_id, trader, side, price, quantity)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (body.instrument_id, body.trader, body.side, body.price, body.quantity),
        )
        order = cursor.fetchone()
        audit.record(cursor, "order", order["id"], "placed", body.model_dump())
        order, trades = match(cursor, order)
        return {"order": order, "trades": trades}


@router.patch("/{order_id}", response_model=OrderExecution, responses={
    **NOT_FOUND, 409: {"description": "Order is not live, trading halted, or quantity at or below filled"},
})
def amend_order(order_id: int, body: OrderUpdate):
    """Change the price or total quantity of a live order.

    Lowering the quantity keeps the order's place in the queue. Changing the price or
    raising the quantity sends it to the back, as on real exchanges. A new price can
    cross the book and trade immediately.
    """
    with db.transaction() as cursor:
        instrument, order = lock_live_order(cursor, order_id)
        require_active(instrument)
        price = order["price"] if body.price is None else body.price
        quantity = order["quantity"] if body.quantity is None else body.quantity
        require_tick(price, instrument)
        if quantity <= order["filled_quantity"]:
            raise HTTPException(409, f"Quantity must exceed the {order['filled_quantity']} already filled")

        loses_priority = price != order["price"] or quantity > order["quantity"]
        cursor.execute(
            """UPDATE orders
               SET price = %s, quantity = %s, updated_at = now(),
                   priority = CASE WHEN %s THEN nextval('order_priority_seq') ELSE priority END
               WHERE id = %s RETURNING *""",
            (price, quantity, loses_priority, order_id),
        )
        amended = cursor.fetchone()
        audit.record(cursor, "order", order_id, "amended", {
            "price": {"from": order["price"], "to": price},
            "quantity": {"from": order["quantity"], "to": quantity},
            "lost_priority": loses_priority,
        })
        amended, trades = match(cursor, amended)
        return {"order": amended, "trades": trades}


@router.delete("/{order_id}", response_model=Order, responses={
    **NOT_FOUND, 409: {"description": "Order already filled or cancelled"},
})
def cancel_order(order_id: int):
    """Cancel the unfilled part of an order. The record stays for the audit trail."""
    with db.transaction() as cursor:
        _, order = lock_live_order(cursor, order_id)
        cursor.execute(
            "UPDATE orders SET status = 'cancelled', updated_at = now() WHERE id = %s RETURNING *",
            (order_id,),
        )
        cancelled = cursor.fetchone()
        audit.record(cursor, "order", order_id, "cancelled", {
            "unfilled_quantity": order["quantity"] - order["filled_quantity"],
        })
        return cancelled
