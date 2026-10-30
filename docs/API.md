# Mini Exchange API reference

Base URL: `http://localhost:8000` (`APP_PORT` in `.env`). Interactive docs: [Swagger UI](http://localhost:8000/docs), [ReDoc](http://localhost:8000/redoc), raw schema at `/openapi.json`.

- Request and response bodies are JSON.
- Prices are exact decimals. Send them as strings (`"1000.5"`) or numbers; responses always return strings (`"1000.5000"`).
- Timestamps are UTC, ISO 8601.
- List endpoints accept `limit` (1–500, default 100) and `offset` (0–1,000,000,000, default 0).
- Errors look like `{"detail": "..."}`. Validation errors (422) list each field problem in `detail`.

| Status | Meaning |
| --- | --- |
| 200 / 201 / 204 | OK / created / deleted, no body |
| 404 | The resource does not exist |
| 409 | The request conflicts with the current state (duplicate symbol, halted trading, order no longer live) |
| 422 | Invalid input (wrong type, out of range, price off the tick size, text the database can't store such as a NUL character) |
| 503 | Database unavailable |

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | API and database status |
| GET | `/instruments` | List instruments |
| GET | `/instruments/{id}` | Get one instrument |
| POST | `/instruments` | Create an instrument |
| PATCH | `/instruments/{id}` | Rename, halt or resume an instrument |
| DELETE | `/instruments/{id}` | Delete an instrument that has no orders |
| GET | `/instruments/{id}/book` | Order book: price levels, best bid and ask, spread, last price |
| GET | `/orders` | List orders |
| GET | `/orders/{id}` | Get one order |
| POST | `/orders` | Place a limit order (matches immediately) |
| PATCH | `/orders/{id}` | Amend price or quantity |
| DELETE | `/orders/{id}` | Cancel an order |
| GET | `/trades` | List trades |
| GET | `/trades/{id}` | Get one trade |
| GET | `/audit-events` | Read the audit trail |

---

## Health

### `GET /health`
`200` → `{"status": "ok", "database": "ok"}`. Returns `503` if PostgreSQL cannot be reached. Docker Compose calls this endpoint for the backend healthcheck.

## Instruments

An instrument is something that can be traded, such as a company share.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | integer | Generated |
| `symbol` | string | 1–10 characters: `A-Z`, digits, `.`; starts with a letter. Unique. Input is trimmed and uppercased |
| `name` | string | 1–100 characters |
| `currency` | string | 3-letter code, default `KZT` |
| `tick_size` | decimal | Price step, default `0.01`. Every order price must be a multiple of it |
| `is_active` | boolean | `false` means trading is halted |
| `created_at` | timestamp | Generated |

### `GET /instruments`
Query: `is_active` (optional boolean), `limit`, `offset`. Sorted by symbol. `200` → array of instruments.

### `GET /instruments/{id}`
`200` → instrument. `404` if missing.

### `POST /instruments`
```json
{"symbol": "KSPI", "name": "Kaspi.kz", "currency": "KZT", "tick_size": "1"}
```
`201` → created instrument. `409` if the symbol exists. `422` on invalid fields.

### `PATCH /instruments/{id}`
Send at least one of `name` and `is_active`:
```json
{"name": "Kaspi.kz JSC"}
```
```json
{"is_active": false}
```
`200` → updated instrument. While `is_active` is false, new orders and amendments return `409`; cancellations still work.

### `DELETE /instruments/{id}`
`204` on success. `409` if the instrument has any orders: trading history is never deleted, so halt it instead.

### `GET /instruments/{id}/book`
Query: `depth` (1–100, default 10): price levels per side.
```json
{
  "instrument_id": 1,
  "symbol": "KSPI",
  "bids": [{"price": "151000.0000", "quantity": 40, "orders": 2}],
  "asks": [{"price": "152000.0000", "quantity": 30, "orders": 1}],
  "best_bid": "151000.0000",
  "best_ask": "152000.0000",
  "spread": "1000.0000",
  "last_price": "152000.0000"
}
```
`bids` are sorted highest price first and `asks` lowest first. `quantity` is the total unfilled quantity at that price; it can exceed the 1,000,000,000 limit of a single order.

## Orders

| Field | Type | Notes |
| --- | --- | --- |
| `id` | integer | Generated |
| `instrument_id` | integer | Instrument to trade |
| `trader` | string | 1–50 characters: letters, digits, `_ . -` |
| `side` | `buy` \| `sell` | |
| `price` | decimal | Limit price, > 0, multiple of `tick_size` |
| `quantity` | integer | Total quantity, 1 to 1,000,000,000 |
| `filled_quantity` | integer | Quantity traded so far |
| `remaining_quantity` | integer | `quantity − filled_quantity`; 0 once cancelled |
| `status` | string | `open`, `partially_filled`, `filled`, `cancelled` |
| `created_at`, `updated_at` | timestamp | |

### `GET /orders`
Query: `instrument_id`, `trader`, `side`, `status` (all optional), `limit`, `offset`. Newest first.

### `GET /orders/{id}`
`200` → order. `404` if missing.

### `POST /orders`
```json
{"instrument_id": 1, "trader": "carol", "side": "buy", "price": "152000", "quantity": 120}
```
The order is matched right away against the opposite side of the book. Anything left unfilled stays in the book.
`201` →
```json
{
  "order": {"id": 3, "status": "filled", "quantity": 120, "filled_quantity": 120, "remaining_quantity": 0, "...": "..."},
  "trades": [
    {"id": 1, "buy_order_id": 3, "sell_order_id": 2, "price": "151500.0000", "quantity": 50, "aggressor_side": "buy", "...": "..."},
    {"id": 2, "buy_order_id": 3, "sell_order_id": 1, "price": "152000.0000", "quantity": 70, "aggressor_side": "buy", "...": "..."}
  ]
}
```
Errors: `404` unknown instrument, `409` trading halted, `422` invalid input or price off the tick size.

### `PATCH /orders/{id}`
Send at least one of `price` and `quantity`. `quantity` is the new **total**, so it must be greater than `filled_quantity`.
```json
{"price": "151800"}
```
- Lowering the quantity keeps the order's place in the queue.
- Changing the price or raising the quantity sends the order to the back of the queue.
- A new price that crosses the book trades immediately.

`200` → `{"order": ..., "trades": [...]}`, the same shape as `POST`. `409` if the order is filled or cancelled, trading is halted, or the quantity is not above the filled amount.

### `DELETE /orders/{id}`
Cancels the unfilled part. The order record is kept, with status `cancelled`, for the audit trail.
`200` → cancelled order. `409` if it is already filled or cancelled.

## Trades

Trades are created only by matching. They cannot be created, edited or deleted through the API.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | integer | |
| `instrument_id` | integer | |
| `buy_order_id`, `sell_order_id` | integer | The two matched orders |
| `price` | decimal | Price of the order that was already resting in the book |
| `quantity` | integer | |
| `aggressor_side` | `buy` \| `sell` | Side of the incoming order |
| `executed_at` | timestamp | |

### `GET /trades`
Query: `instrument_id`, `order_id` (trades where the order bought or sold), `limit`, `offset`. Newest first.

### `GET /trades/{id}`
`200` → trade. `404` if missing.

## Audit trail

### `GET /audit-events`
Query: `entity_type` (`instrument`, `order`, `trade`), `entity_id`, `action` (one of the actions below), `limit`, `offset`. Newest first.

| `entity_type` | Actions |
| --- | --- |
| `instrument` | `created`, `updated`, `deleted` |
| `order` | `placed`, `filled`, `amended`, `cancelled` |
| `trade` | `executed` |

```json
{"id": 10, "entity_type": "order", "entity_id": 1, "action": "amended",
 "data": {"price": {"from": "152000.0000", "to": "151800"}, "quantity": {"from": 100, "to": 100}, "lost_priority": true},
 "created_at": "2026-10-30T18:16:59.818010Z"}
```
Each event is written in the same database transaction as the change it describes. A database trigger rejects `UPDATE` and `DELETE` on this table.
