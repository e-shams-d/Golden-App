# Alembic migrations

The M1 baseline revision is deliberately empty and creates no application or
financial tables. It proves deterministic Alembic wiring and establishes the
expected schema revision marker. Future schema changes must be module-owned,
manually reviewed, and accompanied by PostgreSQL migration tests.
