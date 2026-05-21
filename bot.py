"""MACD momentum trading bot — Alpaca paper trading (entry point).

Skeleton only: structure and the daily run sequence (STRATEGY.md §7) are in
place as comments; no trading logic is implemented yet. See STRATEGY.md for the
authoritative spec and CLAUDE.md for the non-negotiable rules (paper-only, no
silent failures, idempotency, Alpaca as source of truth for positions).
"""

import argparse
import logging
import sys

from db import init_db
from signals import compute_macd

logger = logging.getLogger("bot")

# Trading universe (STRATEGY.md §2), grouped by the spec's categories. PLTR is
# listed under both "AI & Semiconductors" and "Broader Tech & Software"; it
# appears once here per the spec's dedup note.
#
# NOTE: §2 labels this "75 unique tickers after PLTR deduplication", but the
# actual deduplicated list is 78 (the §2 sub-counts sum to 79; minus the one
# PLTR duplicate = 78). Kept at 78 by decision; the "75" in §2 is a stale label.
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
    # Metals & Mining (10)
    "NEM", "GOLD", "FCX", "SCCO", "AA", "X", "CLF", "NUE", "ALB", "RIO",
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
    # 1. Pull daily bars for every ticker in UNIVERSE (last ~60 bars for MACD warmup).
    # 2. Compute MACD for each ticker via signals.compute_macd().
    # 3. Identify fresh signals (crossovers on the most recently closed bar).
    # 4. Pull current positions from Alpaca (source of truth; reconcile vs the DB).
    # 5. Check exit conditions for held positions (signal exit, 60-day time stop).
    # 6. Submit exit orders first, then entry orders up to the concurrency cap (§5).
    #    In --dry-run, print intended orders instead of submitting them to Alpaca.
    # 7. Write all activity (signals, orders, fills, positions, run) to SQLite via db.
    # 8. Send the daily Slack summary.
    raise NotImplementedError("bot.main is not implemented yet")


if __name__ == "__main__":
    args = parse_args()
    setup_logging()
    main(dry_run=args.dry_run)
