"""SQLite schema and initialization for the trading bot.

Implements the logging schema defined in STRATEGY.md §8. This database is the
bot's local audit log; per CLAUDE.md, Alpaca remains the source of truth for
positions and the local `positions` table is reconciled against it.
"""

import sqlite3

# One CREATE statement per table, in the order defined in STRATEGY.md §8.
# IF NOT EXISTS keeps init_db() idempotent — safe to call on every run.
_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS signals (
      id INTEGER PRIMARY KEY,
      timestamp TEXT NOT NULL,
      ticker TEXT NOT NULL,
      signal_type TEXT NOT NULL,
      macd REAL,
      signal_line REAL,
      histogram REAL,
      bar_close REAL,
      action_taken TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY,
      timestamp TEXT NOT NULL,
      ticker TEXT NOT NULL,
      side TEXT NOT NULL,
      qty INTEGER NOT NULL,
      order_type TEXT NOT NULL,
      alpaca_order_id TEXT,
      status TEXT,
      stop_price REAL,
      limit_price REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fills (
      id INTEGER PRIMARY KEY,
      timestamp TEXT NOT NULL,
      ticker TEXT NOT NULL,
      side TEXT NOT NULL,
      qty INTEGER NOT NULL,
      fill_price REAL NOT NULL,
      alpaca_fill_id TEXT,
      alpaca_order_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
      id INTEGER PRIMARY KEY,
      ticker TEXT NOT NULL,
      entry_date TEXT NOT NULL,
      entry_price REAL NOT NULL,
      qty INTEGER NOT NULL,
      exit_date TEXT,
      exit_price REAL,
      exit_reason TEXT,
      pnl_dollars REAL,
      pnl_percent REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS errors (
      id INTEGER PRIMARY KEY,
      timestamp TEXT NOT NULL,
      function TEXT,
      exception TEXT,
      traceback TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
      id INTEGER PRIMARY KEY,
      timestamp TEXT NOT NULL,
      status TEXT NOT NULL,
      signals_count INTEGER,
      orders_placed INTEGER,
      open_positions INTEGER,
      duration_seconds REAL
    )
    """,
)


def init_db(conn: sqlite3.Connection) -> None:
    """Create all six tables from STRATEGY.md §8 if they don't already exist.

    Idempotent and non-destructive: calling this on an existing database
    leaves current tables and data untouched. It does not perform migrations.

    Args:
        conn: An open SQLite connection (file-backed or ``:memory:``).
    """
    cur = conn.cursor()
    for statement in _SCHEMA:
        cur.execute(statement)
    conn.commit()
