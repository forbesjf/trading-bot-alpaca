<<<<<<< HEAD
# trading-bot-alpaca
Autonomous MACD momentum trading bot — signal generation, order execution, position reconciliation, and daily Slack reporting against Alpaca's paper trading API.
=======
# Trading Bot

Algorithmic trading bot running a MACD momentum strategy in an **Alpaca paper trading account**.

See [`STRATEGY.md`](STRATEGY.md) for the full strategy specification and [`CLAUDE.md`](CLAUDE.md) for development conventions.

> **Paper trading only.** This bot trades exclusively against Alpaca's paper API. It does not — and must not — route to live trading.

## Requirements

- Python 3.11+
- An Alpaca account with paper trading API keys
- A Slack incoming webhook URL

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create your local environment file from the template:

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` and set:
   - `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — your paper trading keys
   - `SLACK_WEBHOOK_URL` — your Slack incoming webhook
   - Leave `ALPACA_BASE_URL` as the paper endpoint.

   `.env` is gitignored — never commit it.

## Running

> `bot.py` is not implemented yet.

Once built, the bot runs once daily after market close:

```bash
python bot.py            # paper run
python bot.py --dry-run  # compute signals and print intended orders without placing any
```

## Tests

```bash
pytest
```

## Scheduling

Designed to run via cron at 4:15pm ET on trading days (STRATEGY.md §7):

```
15 16 * * 1-5 cd /path/to/trading-bot && .venv/bin/python bot.py >> bot.log 2>&1
```

(Assumes the host clock is in ET; adjust if the host runs in UTC.)
>>>>>>> eff1ef8 (feat: scaffold repo, verified SQLite schema, 8 tests passing)
