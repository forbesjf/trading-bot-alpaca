"""Tests for the SQLite schema in db.py against STRATEGY.md §8."""

import sqlite3

import pytest

from db import init_db

# Expected tables and their columns, in definition order, per STRATEGY.md §8.
EXPECTED_SCHEMA: dict[str, list[str]] = {
    "signals": [
        "id", "timestamp", "ticker", "signal_type", "macd",
        "signal_line", "histogram", "bar_close", "action_taken",
    ],
    "orders": [
        "id", "timestamp", "ticker", "side", "qty", "order_type",
        "alpaca_order_id", "status", "stop_price", "limit_price",
    ],
    "fills": [
        "id", "timestamp", "ticker", "side", "qty", "fill_price",
        "alpaca_fill_id", "alpaca_order_id",
    ],
    "positions": [
        "id", "ticker", "entry_date", "entry_price", "qty", "exit_date",
        "exit_price", "exit_reason", "pnl_dollars", "pnl_percent",
    ],
    "errors": ["id", "timestamp", "function", "exception", "traceback"],
    "runs": [
        "id", "timestamp", "status", "signals_count", "orders_placed",
        "open_positions", "duration_seconds",
    ],
}


@pytest.fixture
def conn() -> sqlite3.Connection:
    """An in-memory database with the schema initialized."""
    connection = sqlite3.connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def test_all_six_tables_exist(conn: sqlite3.Connection) -> None:
    """init_db() creates exactly the six tables from §8."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    tables = {row[0] for row in rows}
    assert tables == set(EXPECTED_SCHEMA)


@pytest.mark.parametrize("table", EXPECTED_SCHEMA)
def test_table_has_expected_columns(conn: sqlite3.Connection, table: str) -> None:
    """Each table's columns match §8, in order."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    columns = [row[1] for row in rows]  # row[1] is the column name
    assert columns == EXPECTED_SCHEMA[table]


def test_init_db_is_idempotent(conn: sqlite3.Connection) -> None:
    """Calling init_db() again on the same connection does not raise."""
    init_db(conn)  # second call; fixture already called it once
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    assert {row[0] for row in rows} == set(EXPECTED_SCHEMA)
