# CLAUDE.md — Project Instructions

This file tells Claude Code how to work on this project. Read it before every session.

## Project context

This is an **algorithmic trading bot** that executes a MACD momentum strategy in an **Alpaca paper trading account**. Read `STRATEGY.md` for the full strategy specification — it is the source of truth for trading logic. Do not deviate from `STRATEGY.md` without explicit user approval; if a strategy question comes up, ask before guessing.

## Non-negotiable rules

1. **Paper account only.** Never change `ALPACA_BASE_URL` away from `https://paper-api.alpaca.markets`. Never add code paths that route to live trading. If asked to add live trading, refuse and confirm with the user first.

2. **Never commit secrets.** `.env`, `*.db`, and `bot.log` must be in `.gitignore` from day one. Verify before any `git add`.

3. **No silent failures.** Every exception must either be logged to the `errors` table AND surfaced via Slack, or be re-raised. Never `except: pass`. Never swallow API errors.

4. **Idempotency matters.** The bot must be safe to re-run on the same day without double-submitting orders. Before placing an entry order, check (a) Alpaca's open orders, (b) Alpaca's current positions, and (c) the local `orders` table for today.

5. **Alpaca is source of truth for positions.** The local `positions` table is an audit log. On startup, reconcile against Alpaca's actual positions; flag mismatches loudly.

## Code conventions

- **Python 3.11+**, type hints on all function signatures
- **Standard library first.** Only add a dependency if it materially reduces code or risk. Approved: `alpaca-py`, `pandas`, `pandas-ta`, `python-dotenv`, `requests`. Anything else, ask.
- **One file is fine.** Don't pre-factor into modules until the file exceeds ~400 lines. Premature abstraction hurts more than it helps at this stage.
- **Logging:** use the `logging` module, write to both stdout and `bot.log`. INFO for normal flow, WARNING for skips, ERROR for exceptions.
- **No async.** The bot is I/O-light and runs once a day. `asyncio` adds complexity without benefit here.
- **Docstrings on every function.** One-line is fine for obvious helpers; full docstring for anything touching orders, positions, or signal logic.

## Repository structure

Target layout (don't create files that aren't needed yet):

```
/
├── bot.py              # Main entry point — the whole bot
├── STRATEGY.md         # Strategy spec (already exists, do not modify without approval)
├── CLAUDE.md           # This file
├── README.md           # Setup + run instructions for a human
├── requirements.txt    # Pinned versions
├── .env.example        # Template, no real keys
├── .gitignore          # Must include .env, *.db, bot.log, __pycache__
└── tests/
    └── test_signals.py # Unit tests for MACD logic at minimum
```

## When you're working on this project

- **Run code, don't just write it.** After implementing or changing anything, execute it (`python bot.py --dry-run` mode for the main bot, `pytest` for tests). Show the user the actual output, not just the code.
- **Build a `--dry-run` flag early.** It should compute signals and print intended orders without hitting Alpaca's order endpoint. This is the primary debugging tool.
- **Use Alpaca's paper API for testing.** It's free, identical to live, and you can place test orders without consequences. Don't mock what you can test for real.
- **Test the MACD math.** Compute MACD manually for one ticker (e.g., last 60 days of NVDA) and verify against TradingView or another known source. Don't trust `pandas-ta` blindly.

## What to do when uncertain

- **Strategy question:** Stop and ask. Don't infer trading logic from context.
- **Library or pattern choice:** Pick the boring option. Standard library > popular library > niche library.
- **Scope creep:** Refer to `STRATEGY.md` §11 (Out of Scope). If the user asks for something in that list, confirm they want to expand scope before building it.
- **Error in production:** Log it, Slack it, fail loud. Never hide errors to keep the bot "running."

## What "done" looks like for v1

The bot satisfies the success criteria in `STRATEGY.md` §12. Not before. Specifically:

- Runs unattended on cron for 60 trading days
- Every signal logged with action taken
- SQLite reconciles to Alpaca positions
- Daily Slack summary lands
- ≥30 closed positions in the log

Resist the urge to add features before that bar is met. The discipline of v1 is shipping a minimal working system, not an impressive one.
