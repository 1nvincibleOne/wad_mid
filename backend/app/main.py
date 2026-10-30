import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from . import db
from .routers import audit_events, instruments, orders, trades
from .schemas import Health

logger = logging.getLogger("uvicorn.error")

DESCRIPTION = """
A small stock exchange: list instruments, place limit orders, and watch them match.

* Orders match by **price-time priority**: the best price fills first, then the earliest order.
* Each trade executes at the resting order's price.
* Every change is written to an **append-only audit trail** in the same transaction.
* Prices are exact decimals and are returned as strings.
"""


@asynccontextmanager
async def lifespan(app):
    db.initialize()
    yield


app = FastAPI(title="Mini Exchange API", version="1.0.0", description=DESCRIPTION, lifespan=lifespan)
app.include_router(instruments.router)
app.include_router(orders.router)
app.include_router(trades.router)
app.include_router(audit_events.router)


@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(request, exc):
    logger.error("Database error: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(psycopg.DataError)
async def invalid_value(request, exc):
    # Values that pass validation but that PostgreSQL can't store, such as text containing NUL.
    logger.warning("Rejected value: %s", exc)
    return JSONResponse(status_code=422, content={"detail": "A value cannot be stored by the database"})


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/health", response_model=Health, tags=["Health"])
def health():
    """Liveness check used by Docker Compose; also confirms the database answers."""
    with db.transaction() as cursor:
        cursor.execute("SELECT 1")
    return {"status": "ok", "database": "ok"}
