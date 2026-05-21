"""MACD momentum trading bot — Alpaca paper trading (entry point).

Skeleton only: structure and the daily run sequence (STRATEGY.md §7) are in
place as comments; no trading logic is implemented yet. See STRATEGY.md for the
authoritative spec and CLAUDE.md for the non-negotiable rules (paper-only, no
silent failures, idempotency, Alpaca as source of truth for positions).
"""

import argparse
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from alpaca_client import data_client, trading_client
from db import init_db
from signals import compute_macd

logger = logging.getLogger("bot")

# Number of most-recent daily bars to keep per ticker. MACD (26/9) needs ~34
# bars to warm up; 60 gives comfortable headroom (STRATEGY.md §7 step 1).
LOOKBACK_BARS = 60

# Local SQLite audit log (STRATEGY.md §8). Gitignored.
DB_PATH = "bot.db"

# Position sizing & risk (STRATEGY.md §5/§6).
POSITION_SIZE_DOLLARS = 3000.0  # fixed $ per trade regardless of equity (§5)
MAX_POSITIONS = 10              # max concurrent positions (§5)
STOP_LOSS_PCT = 0.08           # bracket stop-loss, -8% from entry (§6)
TAKE_PROFIT_PCT = 0.20         # bracket take-profit, +20% from entry (§6)
TIME_STOP_DAYS = 60            # calendar-day time stop (§6)

# Trading universe (STRATEGY.md §2), grouped by the spec's categories. PLTR is
# listed under both "AI & Semiconductors" and "Broader Tech & Software"; it
# appears once here per the spec's dedup note.
#
# NOTE: §2 labels this "75 unique tickers after PLTR deduplication". The
# deduplicated list is 78 (§2 sub-counts sum to 79, minus the one PLTR
# duplicate). X (US Steel) was then removed after it returned no market data
# (delisted), leaving 77 active tickers traded here.
UNIVERSE: tuple[str, ...] = (
    # AI & Semiconductors (20)
    "NVDA", "AMD", "AVGO", "TSM", "ASML", "MU", "INTC", "QCOM", "MRVL", "ARM",
    "SMCI", "ANET", "CRWV", "VRT", "DELL", "HPE", "ORCL", "IBM", "PLTR", "AI",
    # Hyperscalers & Mega-Tech (12)
    "MSFT", "GOOGL", "AMZN", "META", "AAPL", "TSLA", "NFLX", "CRM", "ADBE",
    "NOW", "SNOW", "DDOG",
    # Broader Tech & Software (8 listed; PLTR deduplicated — see AI group)
    "NET", "CRWD", "PANW", "COIN", "MSTR", "UBER", "SHOP",
    # Energy (12)
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY", "PSX", "MPC", "VLO", "HAL",
    "BKR", "FANG",
    # Metals & Mining (9; X / US Steel removed — delisted, no market data)
    "NEM", "GOLD", "FCX", "SCCO", "AA", "CLF", "NUE", "ALB", "RIO",
    # Commodity & Sector ETFs (5)
    "GLD", "USO", "DBC", "XLE", "XME",
    # Agriculture (3)
    "DE", "ADM", "MOS",
    # Financials (4)
    "JPM", "GS", "V", "BLK",
    # Healthcare (2)
    "LLY", "UNH",
    # Industrial (1)
    "CAT",
    # Benchmarks (2)
    "SPY", "QQQ",
)


def fetch_daily_bars(
    symbols: list[str], lookback: int = LOOKBACK_BARS
) -> dict[str, pd.DataFrame]:
    """Pull the last ``lookback`` daily bars for each symbol from Alpaca.

    Uses the IEX feed (free tier) with split adjustment. Requests a generous
    calendar window to cover ``lookback`` *trading* days, then keeps only the
    most recent ``lookback`` bars per symbol.

    Args:
        symbols: Ticker symbols to fetch.
        lookback: Number of most-recent daily bars to keep per symbol.

    Returns:
        Mapping of symbol -> DataFrame (indexed by timestamp, with OHLCV
        columns). Symbols with no returned data are omitted.
    """
    # ~1.4 calendar days per trading day; pad generously for holidays.
    start = datetime.now(timezone.utc) - timedelta(days=lookback * 2 + 15)
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        adjustment=Adjustment.SPLIT,
        feed=DataFeed.IEX,
    )
    barset = data_client.get_stock_bars(request)
    frame = barset.df
    if frame.empty:
        return {}

    bars: dict[str, pd.DataFrame] = {}
    for symbol in frame.index.get_level_values(0).unique():
        bars[symbol] = frame.loc[symbol].tail(lookback)
    return bars


def _report_bars(bars: dict[str, pd.DataFrame], requested: list[str]) -> None:
    """Log a summary of fetched bars: coverage, counts, and a sample."""
    missing = [s for s in requested if s not in bars]
    counts = {s: len(df) for s, df in bars.items()}
    logger.info(
        "Step 1: fetched bars for %d/%d tickers", len(bars), len(requested)
    )
    if counts:
        logger.info(
            "  bars per ticker: min=%d max=%d",
            min(counts.values()),
            max(counts.values()),
        )
    if missing:
        logger.warning("  no data for %d ticker(s): %s", len(missing), ", ".join(missing))
    short = [s for s, n in counts.items() if n < LOOKBACK_BARS]
    if short:
        logger.warning(
            "  fewer than %d bars for %d ticker(s): %s",
            LOOKBACK_BARS,
            len(short),
            ", ".join(f"{s}({counts[s]})" for s in short),
        )
    for symbol in list(bars)[:5]:
        df = bars[symbol]
        last = df.iloc[-1]
        logger.info(
            "  sample %-5s last bar %s close=%.2f",
            symbol,
            df.index[-1].date(),
            last["close"],
        )


def compute_signals(bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Compute MACD (12/26/9) and crossover flags for each ticker's bars.

    Args:
        bars: Mapping of symbol -> daily-bar DataFrame (must have a ``close``).

    Returns:
        Mapping of symbol -> the DataFrame returned by signals.compute_macd().
    """
    return {symbol: compute_macd(df) for symbol, df in bars.items()}


def _report_signals(signals: dict[str, pd.DataFrame]) -> None:
    """Log a summary of computed MACD: warmed coverage and a sample."""
    warmed = [s for s, df in signals.items() if pd.notna(df["macd"].iloc[-1])]
    logger.info(
        "Step 2: computed MACD for %d ticker(s); %d warmed on the last bar",
        len(signals),
        len(warmed),
    )
    for symbol in list(signals)[:5]:
        last = signals[symbol].iloc[-1]
        logger.info(
            "  sample %-5s macd=%+.3f signal=%+.3f hist=%+.3f",
            symbol,
            last["macd"],
            last["signal"],
            last["histogram"],
        )


def find_fresh_bullish_crossovers(signals: dict[str, pd.DataFrame]) -> list[str]:
    """Return tickers with a bullish crossover on their most recent bar.

    A "fresh" signal is one where the MACD crossed above the signal line on the
    last (most recently closed) daily bar — i.e. STRATEGY.md §3 entry condition
    1. Result is sorted alphabetically to match the §5 tiebreaker.

    Args:
        signals: Mapping of symbol -> signals.compute_macd() output.

    Returns:
        Alphabetically sorted list of symbols with a fresh bullish crossover.
    """
    fresh = [
        symbol
        for symbol, df in signals.items()
        if bool(df["bullish_crossover"].iloc[-1])
    ]
    return sorted(fresh)


def _report_crossovers(
    fresh: list[str],
    signals: dict[str, pd.DataFrame],
    bars: dict[str, pd.DataFrame],
) -> None:
    """Log the fresh bullish crossovers as candidate buy signals."""
    logger.info(
        "Step 3: %d fresh bullish crossover(s) on the most recent bar", len(fresh)
    )
    for symbol in fresh:
        sig = signals[symbol].iloc[-1]
        close = bars[symbol]["close"].iloc[-1]
        logger.info(
            "  BUY signal %-5s @ $%.2f | macd=%+.3f signal=%+.3f hist=%+.3f",
            symbol,
            close,
            sig["macd"],
            sig["signal"],
            sig["histogram"],
        )


def get_alpaca_positions() -> dict[str, int]:
    """Return current Alpaca positions as ``{symbol: qty}``.

    Alpaca is the source of truth for positions (CLAUDE.md rule #5).
    """
    return {p.symbol: int(p.qty) for p in trading_client.get_all_positions()}


def get_db_open_positions(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return open positions from the local DB (``exit_date IS NULL``).

    Args:
        conn: Open SQLite connection.

    Returns:
        Mapping of ticker -> ``{"qty": int, "entry_date": str}``.
    """
    rows = conn.execute(
        "SELECT ticker, qty, entry_date FROM positions WHERE exit_date IS NULL"
    ).fetchall()
    return {r[0]: {"qty": int(r[1]), "entry_date": r[2]} for r in rows}


def reconcile_positions(alpaca: dict[str, int], db: dict[str, dict]) -> None:
    """Compare Alpaca positions against the DB audit log; warn on any mismatch.

    Alpaca is authoritative; the DB is an audit log that should match it. Per
    CLAUDE.md rule #5, mismatches are flagged loudly (WARNING) rather than
    silently corrected.
    """
    only_alpaca = sorted(set(alpaca) - set(db))
    only_db = sorted(set(db) - set(alpaca))
    qty_mismatch = sorted(s for s in set(alpaca) & set(db) if alpaca[s] != db[s]["qty"])

    logger.info(
        "Step 4: %d Alpaca position(s), %d open DB position(s)", len(alpaca), len(db)
    )
    for s in only_alpaca:
        logger.warning(
            "  reconcile: %s held at Alpaca (qty %d) but not open in DB", s, alpaca[s]
        )
    for s in only_db:
        logger.warning(
            "  reconcile: %s open in DB (qty %d) but not held at Alpaca",
            s,
            db[s]["qty"],
        )
    for s in qty_mismatch:
        logger.warning(
            "  reconcile: %s qty mismatch — Alpaca %d vs DB %d",
            s,
            alpaca[s],
            db[s]["qty"],
        )
    if not (only_alpaca or only_db or qty_mismatch):
        logger.info("  reconcile: Alpaca and DB agree")


def check_exits(
    held: dict[str, int],
    signals: dict[str, pd.DataFrame],
    db_positions: dict[str, dict],
    today: date,
) -> list[dict]:
    """Determine bot-submitted exits for held positions (STRATEGY.md §6).

    Evaluates the two exit paths the bot is responsible for; the bracket
    stop-loss/take-profit legs are handled Alpaca-side and are not considered
    here. First trigger wins, with signal exit taking precedence over time stop:
      - ``signal_exit``: bearish MACD crossover on the most recent bar
      - ``time_stop``: position held >= TIME_STOP_DAYS calendar days

    Args:
        held: Alpaca positions ``{symbol: qty}`` (source of truth).
        signals: Per-symbol compute_macd() output.
        db_positions: Open DB positions, for entry dates.
        today: Date used to measure the holding period.

    Returns:
        List of ``{"ticker", "qty", "reason"}`` dicts, sorted by ticker.
    """
    exits: list[dict] = []
    for symbol in sorted(held):
        reason: str | None = None

        sig = signals.get(symbol)
        if sig is not None and bool(sig["bearish_crossover"].iloc[-1]):
            reason = "signal_exit"

        if reason is None:
            info = db_positions.get(symbol)
            if info and info.get("entry_date"):
                entry = datetime.fromisoformat(info["entry_date"]).date()
                if (today - entry).days >= TIME_STOP_DAYS:
                    reason = "time_stop"
            elif symbol not in db_positions:
                logger.warning(
                    "  exit-check: %s held at Alpaca but missing from DB; "
                    "cannot evaluate time stop",
                    symbol,
                )

        if reason:
            exits.append({"ticker": symbol, "qty": held[symbol], "reason": reason})
    return exits


def _report_exits(exits: list[dict], held: dict[str, int]) -> None:
    """Log held-position count and any exit signals."""
    logger.info(
        "Step 5: %d held position(s); %d exit signal(s)", len(held), len(exits)
    )
    for e in exits:
        logger.info(
            "  EXIT %-5s qty %d | reason=%s", e["ticker"], e["qty"], e["reason"]
        )


def plan_entries(
    fresh: list[str],
    held: dict[str, int],
    exits: list[dict],
    bars: dict[str, pd.DataFrame],
) -> tuple[list[dict], list[dict]]:
    """Plan entry orders from fresh crossovers under §3/§5 constraints.

    Skips tickers already held (no pyramiding, §3), sizes each at a fixed
    POSITION_SIZE_DOLLARS (qty = floor(size / last_close), skipping zero-qty),
    and fills only the slots left under MAX_POSITIONS after accounting for
    exits. ``fresh`` is already alphabetical, which is the §5 tiebreaker.

    Returns:
        ``(entries, skipped)`` — entries as order dicts; skipped as dicts of
        ``{"ticker", "action"}`` where action is a signals-table action_taken
        code (``skipped_held`` / ``skipped_max_positions`` / ``skipped_zero_qty``).
    """
    slots = MAX_POSITIONS - (len(held) - len(exits))

    entries: list[dict] = []
    skipped: list[dict] = []
    for symbol in fresh:
        if symbol in held:
            skipped.append({"ticker": symbol, "action": "skipped_held"})
            continue
        if len(entries) >= slots:
            skipped.append({"ticker": symbol, "action": "skipped_max_positions"})
            continue
        close = float(bars[symbol]["close"].iloc[-1])
        qty = int(POSITION_SIZE_DOLLARS // close)
        if qty == 0:
            skipped.append({"ticker": symbol, "action": "skipped_zero_qty"})
            continue
        entries.append(
            {
                "ticker": symbol,
                "qty": qty,
                "close": close,
                "stop": round(close * (1 - STOP_LOSS_PCT), 2),
                "take_profit": round(close * (1 + TAKE_PROFIT_PCT), 2),
            }
        )
    return entries, skipped


def _report_intended_orders(
    exits: list[dict], entries: list[dict], skipped: list[dict], dry_run: bool
) -> None:
    """Log intended orders: exits first, then entries, then skips."""
    mode = "DRY-RUN — nothing submitted" if dry_run else "LIVE"
    logger.info(
        "Step 6: intended orders (%s) — %d exit(s), %d entry(ies)",
        mode,
        len(exits),
        len(entries),
    )
    for e in exits:
        logger.info(
            "  [EXIT]  market SELL %d %s @ next open | reason=%s",
            e["qty"],
            e["ticker"],
            e["reason"],
        )
    for e in entries:
        logger.info(
            "  [ENTRY] bracket BUY %d %s @ next open (MOO) | est. close $%.2f"
            " | stop $%.2f (-8%%) tp $%.2f (+20%%)",
            e["qty"],
            e["ticker"],
            e["close"],
            e["stop"],
            e["take_profit"],
        )
    for s in skipped:
        logger.info("  [SKIP]  %s — %s", s["ticker"], s["action"])


def build_signal_rows(
    fresh: list[str],
    signals: dict[str, pd.DataFrame],
    bars: dict[str, pd.DataFrame],
    entries: list[dict],
    skipped: list[dict],
) -> list[tuple]:
    """Build ``signals``-table rows for each fresh bullish crossover.

    The action_taken column records whether the signal led to an order or was
    skipped (and why), so the integrity criterion in STRATEGY.md §12 holds:
    every signal has a corresponding action.
    """
    action_by_ticker = {e["ticker"]: "order_placed" for e in entries}
    action_by_ticker.update({s["ticker"]: s["action"] for s in skipped})

    now = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    for ticker in fresh:
        last = signals[ticker].iloc[-1]
        rows.append(
            (
                now,
                ticker,
                "bullish_crossover",
                float(last["macd"]),
                float(last["signal"]),
                float(last["histogram"]),
                float(bars[ticker]["close"].iloc[-1]),
                action_by_ticker[ticker],
            )
        )
    return rows


def build_order_rows(
    exits: list[dict], entries: list[dict], status: str
) -> list[tuple]:
    """Build ``orders``-table rows for intended exits (market) and entries (bracket)."""
    now = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    for e in exits:
        # (timestamp, ticker, side, qty, order_type, alpaca_order_id, status, stop, limit)
        rows.append((now, e["ticker"], "sell", e["qty"], "market", None, status, None, None))
    for e in entries:
        rows.append(
            (now, e["ticker"], "buy", e["qty"], "bracket", None, status, e["stop"], e["take_profit"])
        )
    return rows


def write_activity(
    conn: sqlite3.Connection,
    signal_rows: list[tuple],
    order_rows: list[tuple],
    run_row: tuple,
) -> None:
    """Insert signals, orders, and the run summary into SQLite (one transaction)."""
    conn.executemany(
        "INSERT INTO signals "
        "(timestamp, ticker, signal_type, macd, signal_line, histogram, bar_close, action_taken) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        signal_rows,
    )
    conn.executemany(
        "INSERT INTO orders "
        "(timestamp, ticker, side, qty, order_type, alpaca_order_id, status, stop_price, limit_price) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        order_rows,
    )
    conn.execute(
        "INSERT INTO runs "
        "(timestamp, status, signals_count, orders_placed, open_positions, duration_seconds) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        run_row,
    )
    conn.commit()


def _report_db_writes(conn: sqlite3.Connection) -> None:
    """Read back and log what was persisted, so dry-run shows the actual rows."""
    for table in ("signals", "orders", "runs"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        logger.info("  wrote %d row(s) to %s", count, table)
    for ticker, side, qty, otype, status, stop, limit in conn.execute(
        "SELECT ticker, side, qty, order_type, status, stop_price, limit_price FROM orders"
    ):
        logger.info(
            "    orders row: %-5s %-4s %d %-7s status=%s stop=%s tp=%s",
            ticker, side, qty, otype, status, stop, limit,
        )


def send_slack_summary(message: str, dry_run: bool) -> None:
    """Send the daily summary to Slack, or skip cleanly if unconfigured.

    SLACK_WEBHOOK_URL is optional: if it's unset, log a WARNING and skip (no
    silent failure — the absence is surfaced). In dry-run the message is shown
    but not POSTed.
    """
    logger.info("Step 8: daily Slack summary: %s", message)
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        logger.warning("  SLACK_WEBHOOK_URL not set in .env; Slack notification skipped")
        return
    if dry_run:
        logger.info("  (dry-run) not POSTing; the message above would be sent")
        return
    response = requests.post(webhook, json={"text": message}, timeout=10)
    response.raise_for_status()
    logger.info("  Slack summary sent (HTTP %d)", response.status_code)


def setup_logging() -> None:
    """Configure logging to both stdout and bot.log (STRATEGY.md §10 / CLAUDE.md)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("bot.log"),
        ],
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="MACD momentum trading bot (Alpaca paper trading)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute signals and print intended orders without placing any.",
    )
    return parser.parse_args()


def main(dry_run: bool = False) -> None:
    """Run one daily cycle of the bot.

    Follows the STRATEGY.md §7 sequence. Steps 1-8 run in dry-run; live order
    submission (step 6) is not yet implemented and raises if dry_run is False.
    """
    start_time = datetime.now(timezone.utc)

    # 1. Pull daily bars for every ticker in UNIVERSE (last LOOKBACK_BARS bars).
    bars = fetch_daily_bars(list(UNIVERSE))
    _report_bars(bars, list(UNIVERSE))

    # 2. Compute MACD for each ticker via signals.compute_macd().
    signals = compute_signals(bars)
    _report_signals(signals)

    # 3. Identify fresh bullish crossovers on the most recently closed bar.
    fresh = find_fresh_bullish_crossovers(signals)
    _report_crossovers(fresh, signals, bars)
    # 4. Pull current positions from Alpaca (source of truth) and reconcile vs the DB.
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    alpaca_positions = get_alpaca_positions()
    db_positions = get_db_open_positions(conn)
    reconcile_positions(alpaca_positions, db_positions)

    # 5. Check exit conditions for held positions (signal exit, 60-day time stop).
    today = datetime.now(timezone.utc).date()
    exits = check_exits(alpaca_positions, signals, db_positions, today)
    _report_exits(exits, alpaca_positions)

    # 6. Plan orders (exits first, then entries up to the cap) and, in dry-run,
    #    print them instead of submitting to Alpaca.
    entries, skipped = plan_entries(fresh, alpaca_positions, exits, bars)
    _report_intended_orders(exits, entries, skipped, dry_run)
    if not dry_run:
        raise NotImplementedError("live order submission not implemented yet (step 6)")

    # 7. Persist activity (signals, orders, run summary) to SQLite.
    order_status = "dry_run" if dry_run else "pending"
    signal_rows = build_signal_rows(fresh, signals, bars, entries, skipped)
    order_rows = build_order_rows(exits, entries, order_status)
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    open_positions = len(alpaca_positions)
    run_row = (
        datetime.now(timezone.utc).isoformat(),
        "success",
        len(fresh),
        len(order_rows),
        open_positions,
        duration,
    )
    logger.info("Step 7: persisting activity to SQLite")
    if dry_run:
        # Don't pollute bot.db with orders that were never submitted; write to a
        # throwaway in-memory DB and read it back to show the rows.
        demo = sqlite3.connect(":memory:")
        init_db(demo)
        write_activity(demo, signal_rows, order_rows, run_row)
        _report_db_writes(demo)
        demo.close()
        logger.info("  (dry-run: wrote to in-memory DB; %s untouched)", DB_PATH)
    else:
        write_activity(conn, signal_rows, order_rows, run_row)
        _report_db_writes(conn)

    # 8. Send the daily Slack summary (STRATEGY.md §9).
    summary = (
        f"📊 Bot run OK | {len(fresh)} signals | "
        f"{len(order_rows)} orders | {open_positions} open"
    )
    send_slack_summary(summary, dry_run)

    conn.close()


if __name__ == "__main__":
    args = parse_args()
    setup_logging()
    main(dry_run=args.dry_run)
