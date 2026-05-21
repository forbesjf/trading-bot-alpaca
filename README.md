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

The bot runs once daily after market close:

```bash
python bot.py            # live paper run — submits orders to Alpaca
python bot.py --dry-run  # compute signals and print intended orders without placing any
```

## Tests

```bash
pytest
```

## Scheduling (launchd)

The bot is scheduled with a launchd agent (`com.jackforbes.tradingbot.plist`) so it
runs at **4:15pm ET on weekdays even if the Mac was asleep** at the scheduled time —
launchd runs a missed job on the next wake, unlike cron (STRATEGY.md §7).

> The plist's `Hour` is the Mac's **local** time. It is set to `14:15` for Mountain
> Time (MDT, UTC-6) = 4:15pm ET. Adjust `Hour` if your machine is in another timezone.

Install:

1. Copy the plist into your user LaunchAgents directory:

   ```bash
   cp com.jackforbes.tradingbot.plist ~/Library/LaunchAgents/
   ```

2. Load it:

   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jackforbes.tradingbot.plist
   ```

3. Verify it's registered:

   ```bash
   launchctl print gui/$(id -u)/com.jackforbes.tradingbot | grep -A3 -i calendar
   ```

To update after editing the plist, reload it:

```bash
cp com.jackforbes.tradingbot.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/com.jackforbes.tradingbot
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jackforbes.tradingbot.plist
```

Optional — wake the Mac one minute early so the job runs on time even when asleep:

```bash
sudo pmset repeat wakeorpoweron MTWRF 14:14:00
```
