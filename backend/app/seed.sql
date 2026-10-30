-- Demo instruments, added only while the table is empty (SEED_DEMO_DATA=true).
INSERT INTO instruments (symbol, name, currency, tick_size)
SELECT symbol, name, currency, tick_size
FROM (VALUES
    ('KSPI', 'Kaspi.kz', 'KZT', 1.0),
    ('HSBK', 'Halyk Bank', 'KZT', 0.01),
    ('KZAP', 'Kazatomprom', 'KZT', 1.0),
    ('AAPL', 'Apple Inc.', 'USD', 0.01)
) AS demo (symbol, name, currency, tick_size)
WHERE NOT EXISTS (SELECT 1 FROM instruments);
