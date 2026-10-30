"""Price-time priority matching for limit orders.

Every function expects the caller to hold the instrument's row lock
(see lock_instrument), so only one request changes a given order book at a time.
"""
from fastapi import HTTPException

from . import audit

LIVE = ["open", "partially_filled"]
OPPOSITE = {"buy": "sell", "sell": "buy"}


def lock_instrument(cursor, instrument_id):
    # Concurrent requests for the same instrument wait here until this transaction ends.
    cursor.execute("SELECT * FROM instruments WHERE id = %s FOR UPDATE", (instrument_id,))
    instrument = cursor.fetchone()
    if instrument is None:
        raise HTTPException(404, "Instrument not found")
    return instrument


def require_active(instrument):
    if not instrument["is_active"]:
        raise HTTPException(409, f"Trading in {instrument['symbol']} is halted")


def require_tick(price, instrument):
    if price % instrument["tick_size"] != 0:
        raise HTTPException(422, f"Price must be a multiple of the tick size {instrument['tick_size']}")


def fill(cursor, order_id, quantity):
    # The CASE reads filled_quantity as it was before this UPDATE.
    cursor.execute(
        """UPDATE orders
           SET filled_quantity = filled_quantity + %(qty)s,
               status = CASE WHEN filled_quantity + %(qty)s = quantity
                             THEN 'filled' ELSE 'partially_filled' END,
               updated_at = now()
           WHERE id = %(id)s RETURNING *""",
        {"qty": quantity, "id": order_id},
    )
    return cursor.fetchone()


def match(cursor, order):
    """Trade the incoming order against the opposite side of the book.

    The best price fills first; at equal prices the earliest order fills first.
    Each trade executes at the resting order's price. Returns (order, trades).
    """
    if order["side"] == "buy":
        crosses, best_first = "price <= %s", "price ASC"
    else:
        crosses, best_first = "price >= %s", "price DESC"

    trades = []
    remaining = order["quantity"] - order["filled_quantity"]
    while remaining > 0:
        cursor.execute(
            f"""SELECT * FROM orders
                WHERE instrument_id = %s AND side = %s AND status = ANY(%s) AND {crosses}
                ORDER BY {best_first}, priority LIMIT 1""",
            (order["instrument_id"], OPPOSITE[order["side"]], LIVE, order["price"]),
        )
        resting = cursor.fetchone()
        if resting is None:
            break

        quantity = min(remaining, resting["quantity"] - resting["filled_quantity"])
        buy, sell = (order, resting) if order["side"] == "buy" else (resting, order)
        cursor.execute(
            """INSERT INTO trades (instrument_id, buy_order_id, sell_order_id, price, quantity, aggressor_side)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
            (order["instrument_id"], buy["id"], sell["id"], resting["price"], quantity, order["side"]),
        )
        trade = cursor.fetchone()
        trades.append(trade)
        audit.record(cursor, "trade", trade["id"], "executed", trade)

        for order_id in (resting["id"], order["id"]):
            filled = fill(cursor, order_id, quantity)
            audit.record(cursor, "order", order_id, "filled", {
                "trade_id": trade["id"], "price": trade["price"], "quantity": quantity,
                "filled_quantity": filled["filled_quantity"], "status": filled["status"],
            })
            if order_id == order["id"]:
                order = filled
        remaining -= quantity
    return order, trades
