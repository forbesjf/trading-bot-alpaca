"""MACD momentum trading bot — Alpaca paper trading (entry point).

Skeleton only: structure and the daily run sequence (STRATEGY.md §7) are in
place as comments; no trading logic is implemented yet. See STRATEGY.md for the
authoritative spec and CLAUDE.md for the non-negotiable rules (paper-only, no
silent failures, idempotency, Alpaca as source of truth for positions).
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from alpaca_client import data_client
from db import init_db
from signals import compute_macd

logger = logging.getLogger("bot")

# Number of most-recent daily bars to keep per ticker. MACD (26/9) needs ~34
# bars to warm up; 60 gives comfortable headroom (STRATEGY.md §7 step 1).
LOOKBACK_BARS = 60

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

    The sequence below follows STRATEGY.md §7. Steps are documented as comments
    only; nothing is implemented yet. ``dry_run`` will, once built, compute
    signals and print intended orders without hitting Alpaca's order endpoint.
    """
    # 1. Pull daily bars for every ticker in UNIVERSE (last LOOKBACK_BARS bars).
    bars = fetch_daily_bars(list(UNIVERSE))
    _report_bars(bars, list(UNIVERSE))

    # 2. Compute MACD for each ticker via signals.compute_macd().
    signals = compute_signals(bars)
    _report_signals(signals)

    # 3. Identify fresh bullish crossovers on the most recently closed bar.
    fresh = find_fresh_bullish_crossovers(signals)
    _report_crossovers(fresh, signals, bars)
    # 4. Pull current positions from Alpaca (source of truth; reconcile vs the DB).
    # 5. Check exit conditions for held positions (signal exit, 60-day time stop).
    # 6. Submit exit orders first, then entry orders up to the concurrency cap (§5).
    #    In --dry-run, print intended orders instead of submitting them to Alpaca.
    # 7. Write all activity (signals, orders, fills, positions, run) to SQLite via db.
    # 8. Send the daily Slack summary.


if __name__ == "__main__":
    args = parse_args()
    setup_logging()
    main(dry_run=args.dry_run)
