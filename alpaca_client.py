"""Alpaca client setup for the trading bot — paper trading only.

Reads credentials from .env and constructs the Alpaca trading and market-data
clients. Per CLAUDE.md non-negotiable rule #1 this module is paper-only: it
hard-fails at import if ALPACA_BASE_URL is anything other than the paper
endpoint, and the TradingClient is always created with paper=True. There is no
code path to live trading.
"""

import os

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from alpaca.trading.models import TradeAccount
from dotenv import load_dotenv

load_dotenv()

PAPER_BASE_URL = "https://paper-api.alpaca.markets"

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", PAPER_BASE_URL)


def _require_paper() -> None:
    """Refuse to start unless configured for the Alpaca paper endpoint.

    Belt-and-suspenders enforcement of CLAUDE.md rule #1: even though the
    clients below set paper=True, this guard fails loudly if .env points at a
    non-paper URL or is missing credentials.
    """
    if ALPACA_BASE_URL.rstrip("/") != PAPER_BASE_URL:
        raise RuntimeError(
            f"Refusing to start: ALPACA_BASE_URL is {ALPACA_BASE_URL!r}, but "
            f"this bot is paper-only and requires {PAPER_BASE_URL!r} "
            "(CLAUDE.md non-negotiable rule #1)."
        )
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise RuntimeError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY must both be set in .env."
        )


_require_paper()

# Paper trading client. paper=True routes to paper-api.alpaca.markets and is the
# only mode this bot ever uses.
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

# Market-data client (same endpoint for paper and live — data is read-only).
data_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def get_account() -> TradeAccount:
    """Fetch and return the Alpaca paper account details."""
    return trading_client.get_account()


if __name__ == "__main__":
    account = get_account()
    print("Alpaca paper account — credential smoke test")
    print(f"  status:          {account.status}")
    print(f"  account number:  {account.account_number}")
    print(f"  buying power:    ${float(account.buying_power):,.2f}")
    print(f"  cash:            ${float(account.cash):,.2f}")
    print(f"  portfolio value: ${float(account.portfolio_value):,.2f}")
