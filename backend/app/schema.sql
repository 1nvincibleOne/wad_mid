-- Idempotent: runs on every backend start.

CREATE TABLE IF NOT EXISTS instruments (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE CHECK (symbol ~ '^[A-Z][A-Z0-9.]{0,9}$'),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    currency CHAR(3) NOT NULL DEFAULT 'KZT' CHECK (currency ~ '^[A-Z]{3}$'),
    tick_size NUMERIC(18, 4) NOT NULL DEFAULT 0.01 CHECK (tick_size > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Time priority: a lower number was queued earlier. Amending price or raising
-- quantity takes a new number, which sends the order to the back of the queue.
CREATE SEQUENCE IF NOT EXISTS order_priority_seq;

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments (id) ON DELETE RESTRICT,
    trader TEXT NOT NULL CHECK (trader ~ '^[A-Za-z0-9_.-]{1,50}$'),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    price NUMERIC(18, 4) NOT NULL CHECK (price > 0),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    filled_quantity INTEGER NOT NULL DEFAULT 0 CHECK (filled_quantity BETWEEN 0 AND quantity),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'partially_filled', 'filled', 'cancelled')),
    priority BIGINT NOT NULL DEFAULT nextval('order_priority_seq'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Covers the matching query: resting orders of one side, best price first.
CREATE INDEX IF NOT EXISTS orders_book_idx ON orders (instrument_id, side, price, priority)
    WHERE status IN ('open', 'partially_filled');

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments (id) ON DELETE RESTRICT,
    buy_order_id INTEGER NOT NULL REFERENCES orders (id),
    sell_order_id INTEGER NOT NULL REFERENCES orders (id),
    price NUMERIC(18, 4) NOT NULL CHECK (price > 0),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    aggressor_side TEXT NOT NULL CHECK (aggressor_side IN ('buy', 'sell')),
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS trades_instrument_idx ON trades (instrument_id, id);

-- No foreign keys: the trail must outlive the rows it describes.
CREATE TABLE IF NOT EXISTS audit_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('instrument', 'order', 'trade')),
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_entity_idx ON audit_events (entity_type, entity_id, id);

-- The database itself rejects edits to the audit trail, whatever the client.
CREATE OR REPLACE FUNCTION reject_audit_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER audit_events_append_only
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION reject_audit_change();
