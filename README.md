# Mini Exchange

A REST API for a small stock exchange, built with FastAPI and PostgreSQL. Traders place limit orders on listed instruments, and the API matches them into trades.

- Price-time priority matching with partial fills. Trades execute at the resting order's price.
- Amending an order follows exchange queue rules. Lowering the quantity keeps its place in the queue; changing the price or raising the quantity moves it to the back.
- Instruments enforce a tick size and can be halted.
- Every change is recorded in an append-only audit log.

## Running locally

Requires Docker with Compose v2.

1. Copy [`.env.example`](.env.example) to `.env` and set `POSTGRES_PASSWORD`.
2. Run `docker compose up --build`.
3. Open the API docs at http://localhost:8000/docs.

The full endpoint reference is in [docs/API.md](docs/API.md). Four demo instruments are added on the first start.

To test every endpoint, import [the Postman collection](postman/mini-exchange.postman_collection.json) and choose Run collection. Later requests reuse IDs from earlier ones, so run it in order. If you change `APP_PORT`, update the collection's `baseUrl` variable.

## Services

| Service | Image | Host port | Purpose |
| --- | --- | --- | --- |
| `backend` | built from [`backend/Dockerfile`](backend/Dockerfile) | 8000 (`APP_PORT`) | FastAPI application |
| `db` | `postgres:17-alpine` | none | PostgreSQL database |
| `adminer` | `adminer:4.8.1` | 8080 (`ADMINER_PORT`) | Database web UI |

The services share the `exchange` network, and PostgreSQL stores its data in the named volume `pgdata`. To sign in to Adminer, choose the PostgreSQL system and server `db`, then use the database credentials from `.env`.
