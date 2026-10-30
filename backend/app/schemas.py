from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import Query
from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, computed_field, model_validator,
)


def normalize_code(value):
    # Runs before the pattern check, so " kspi " is accepted as "KSPI".
    return value.strip().upper() if isinstance(value, str) else value


Symbol = Annotated[str, BeforeValidator(normalize_code), StringConstraints(pattern=r"^[A-Z][A-Z0-9.]{0,9}$")]
Currency = Annotated[str, BeforeValidator(normalize_code), StringConstraints(pattern=r"^[A-Z]{3}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Trader = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.-]{1,50}$")]
# Exact decimals, never floats; matches NUMERIC(18, 4) in the database.
Price = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]
Quantity = Annotated[int, Field(gt=0, le=1_000_000_000)]
Side = Literal["buy", "sell"]
OrderStatus = Literal["open", "partially_filled", "filled", "cancelled"]
EntityType = Literal["instrument", "order", "trade"]
AuditAction = Literal["created", "updated", "deleted", "placed", "filled", "amended", "cancelled", "executed"]

# Pagination for list endpoints. The offset cap keeps values inside PostgreSQL's bigint.
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0, le=1_000_000_000)]


class InstrumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"symbol": "KSPI", "name": "Kaspi.kz", "currency": "KZT", "tick_size": "1"},
    ]})
    symbol: Symbol
    name: Name
    currency: Currency = "KZT"
    tick_size: Price = Field(Decimal("0.01"), description="Prices must be a multiple of this step.")


class InstrumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"name": "Kaspi.kz JSC"}, {"is_active": False},
    ]})
    name: Name | None = None
    is_active: bool | None = Field(None, description="false halts trading: new orders and amendments are rejected.")

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.is_active is None:
            raise ValueError("Provide name or is_active")
        return self


class Instrument(BaseModel):
    id: int
    symbol: str
    name: str
    currency: str
    tick_size: Decimal
    is_active: bool
    created_at: datetime


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"instrument_id": 1, "trader": "alice", "side": "buy", "price": "152000", "quantity": 10},
    ]})
    instrument_id: int
    trader: Trader
    side: Side
    price: Price = Field(description="Limit price: the most a buyer pays or the least a seller accepts.")
    quantity: Quantity


class OrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"price": "151500"}, {"quantity": 5},
    ]})
    price: Price | None = None
    quantity: Quantity | None = Field(None, description="New total quantity, including what has already filled.")

    @model_validator(mode="after")
    def require_change(self):
        if self.price is None and self.quantity is None:
            raise ValueError("Provide price or quantity")
        return self


class Order(BaseModel):
    id: int
    instrument_id: int
    trader: str
    side: Side
    price: Decimal
    quantity: int
    filled_quantity: int
    status: OrderStatus
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def remaining_quantity(self) -> int:
        return 0 if self.status == "cancelled" else self.quantity - self.filled_quantity


class Trade(BaseModel):
    id: int
    instrument_id: int
    buy_order_id: int
    sell_order_id: int
    price: Decimal
    quantity: int
    aggressor_side: Side = Field(description="Side of the incoming order that crossed the book.")
    executed_at: datetime


class OrderExecution(BaseModel):
    order: Order
    trades: list[Trade] = Field(description="Trades this request executed, in execution order.")


class BookLevel(BaseModel):
    price: Decimal
    quantity: int
    orders: int


class OrderBook(BaseModel):
    instrument_id: int
    symbol: str
    bids: list[BookLevel] = Field(description="Buy orders, highest price first.")
    asks: list[BookLevel] = Field(description="Sell orders, lowest price first.")
    best_bid: Decimal | None
    best_ask: Decimal | None
    spread: Decimal | None
    last_price: Decimal | None


class AuditEvent(BaseModel):
    id: int
    entity_type: EntityType
    entity_id: int
    action: str
    data: dict[str, Any]
    created_at: datetime


class Health(BaseModel):
    status: str
    database: str
