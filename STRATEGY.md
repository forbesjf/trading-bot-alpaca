# Trading Bot Strategy Specification

**Version:** 1.0
**Status:** v1 — Paper trading only
**Last updated:** May 2026

---

## 1. Purpose

Automated execution of a MACD momentum strategy across a curated universe of US equities and ETFs, running in an Alpaca **paper trading account**. The goal of v1 is to validate execution mechanics, logging, and operational reliability — not to optimize alpha. No live capital until the bot has run unsupervised for at least 60 trading days.

---

## 2. Universe (75 tickers)

Theme-weighted toward AI/semiconductors and commodities, with limited diversifier exposure.

### AI & Semiconductors (20)
```
NVDA, AMD, AVGO, TSM, ASML, MU, INTC, QCOM, MRVL, ARM,
SMCI, ANET, CRWV, VRT, DELL, HPE, ORCL, IBM, PLTR, AI
```

### Hyperscalers & Mega-Tech (12)
```
MSFT, GOOGL, AMZN, META, AAPL, TSLA, NFLX, CRM, ADBE, NOW, SNOW, DDOG
```

### Broader Tech & Software (8)
```
PLTR, NET, CRWD, PANW, COIN, MSTR, UBER, SHOP
```
*Note: PLTR appears in AI category — deduplicate to one entry in code.*

### Energy (12)
```
XOM, CVX, COP, EOG, SLB, OXY, PSX, MPC, VLO, HAL, BKR, FANG
```

### Metals & Mining (10)
```
NEM, GOLD, FCX, SCCO, AA, X, CLF, NUE, ALB, RIO
```

### Commodity & Sector ETFs (5)
```
GLD, USO, DBC, XLE, XME
```

### Agriculture (3)
```
DE, ADM, MOS
```

### Financials (4)
```
JPM, GS, V, BLK
```

### Healthcare (2)
```
LLY, UNH
```

### Industrial (1)
```
CAT
```

### Benchmarks (2)
```
SPY, QQQ
```

**Total: 75 unique tickers after PLTR deduplication.**

---

## 3. Signal Logic

### Indicator
Standard MACD on **daily bars**:
- Fast EMA: 12
- Slow EMA: 26
- Signal line EMA: 9

### Entry signal (long only)
A ticker generates a **buy signal** when, on the most recently closed daily bar:
1. MACD line crosses above signal line (bullish crossover), AND
2. MACD histogram > 0, AND
3. Ticker is not currently held, AND
4. Bot is below max concurrent position cap (see §5)

### Exit signal
A held position generates a **sell signal** when:
- MACD line crosses below signal line (bearish crossover)

*Note: bracket order stop-loss and take-profit (§6) execute independently of signal logic via Alpaca's order engine.*

### Shorting
**Not permitted in v1.** Long-only.

---

## 4. Order Execution

### Entry orders
- **Order type:** Bracket order (entry + stop-loss + take-profit)
- **Entry leg:** Market-on-open (MOO) for the next regular trading session
- **Time in force:** DAY

### Exit orders
- **Stop-loss and take-profit:** Handled automatically by the bracket order on Alpaca's side
- **Signal exits:** Submitted by the bot as market orders at next open after a bearish crossover
- **Time-stop exits:** Submitted by the bot as market orders at next open

### Order sizing
Quantity per order = `floor(position_size_dollars / last_close_price)`

If the resulting quantity is 0 (price exceeds position size), skip the signal and log the skip.

---

## 5. Position Sizing & Risk

| Parameter | Value |
|---|---|
| Starting paper balance | $100,000 |
| Position size | 3% of starting equity ($3,000 per trade) |
| Max concurrent positions | 10 |
| Max capital deployed | 30% (10 × 3%) |
| Pyramiding | Not permitted (one position per ticker) |
| Averaging down | Not permitted |

**Position size is fixed at $3,000 regardless of account equity changes during v1.** This keeps sizing predictable for the paper trading evaluation period. Revisit after 60 days.

### Tiebreaker (when more signals fire than open slots)
**Alphabetical by ticker.** Boring and defensible. Replace with a ranking layer in v1.5 if signal selection becomes a bottleneck.

---

## 6. Exit Rules

Four exit paths, first trigger wins:

| Exit type | Trigger | Implementation |
|---|---|---|
| Stop-loss | -8% from entry fill price | Bracket order leg (Alpaca-side) |
| Take-profit | +20% from entry fill price | Bracket order leg (Alpaca-side) |
| Signal exit | MACD bearish crossover | Bot-submitted market order, next open |
| Time stop | 60 calendar days held | Bot-submitted market order, next open |

**Reward-to-risk:** 2.5:1 (20% target / 8% stop).

**Exit reason must be logged** for every closed position. This is critical for post-period analysis.

---

## 7. Operational Cadence

### Run schedule
- **Time:** 4:15pm ET, Monday–Friday
- **Cron:** `15 16 * * 1-5` (assumes host in ET; adjust if UTC)
- **Trigger:** 15 minutes after market close, ensuring all daily bars are final

### Run sequence
1. Pull daily bars for all 75 tickers (last 60 bars for MACD warmup)
2. Compute MACD for each ticker
3. Identify fresh signals (crossovers on the most recent closed bar)
4. Pull current positions from Alpaca
5. Check exit conditions for held positions (signal exit, time stop)
6. Submit exit orders first, then entry orders up to concurrency cap
7. Write all activity to SQLite
8. Send Slack summary

### Health check
Daily 4:20pm ET Slack message: `Bot run OK | N signals | M orders placed | P open positions`. Absence of this message = something broke.

---

## 8. Logging Schema (SQLite)

Database file: `bot.db` in repo root (gitignored).

### Tables

```sql
CREATE TABLE signals (
  id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL,
  ticker TEXT NOT NULL,
  signal_type TEXT NOT NULL,  -- 'bullish_crossover' | 'bearish_crossover'
  macd REAL,
  signal_line REAL,
  histogram REAL,
  bar_close REAL,
  action_taken TEXT  -- 'order_placed' | 'skipped_max_positions' | 'skipped_held' | 'skipped_zero_qty'
);

CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,  -- 'buy' | 'sell'
  qty INTEGER NOT NULL,
  order_type TEXT NOT NULL,  -- 'bracket' | 'market'
  alpaca_order_id TEXT,
  status TEXT,
  stop_price REAL,
  limit_price REAL
);

CREATE TABLE fills (
  id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,
  qty INTEGER NOT NULL,
  fill_price REAL NOT NULL,
  alpaca_fill_id TEXT,
  alpaca_order_id TEXT
);

CREATE TABLE positions (
  id INTEGER PRIMARY KEY,
  ticker TEXT NOT NULL,
  entry_date TEXT NOT NULL,
  entry_price REAL NOT NULL,
  qty INTEGER NOT NULL,
  exit_date TEXT,
  exit_price REAL,
  exit_reason TEXT,  -- 'stop_loss' | 'take_profit' | 'signal_exit' | 'time_stop'
  pnl_dollars REAL,
  pnl_percent REAL
);

CREATE TABLE errors (
  id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL,
  function TEXT,
  exception TEXT,
  traceback TEXT
);

CREATE TABLE runs (
  id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL,
  status TEXT NOT NULL,  -- 'success' | 'partial' | 'failed'
  signals_count INTEGER,
  orders_placed INTEGER,
  open_positions INTEGER,
  duration_seconds REAL
);
```

---

## 9. Notifications (Slack)

Single webhook, posts to one channel. Messages:

| Event | Message format |
|---|---|
| Bullish signal | `🟢 BUY signal: {ticker} @ ${close} | MACD {macd:.2f} > Signal {signal:.2f}` |
| Order filled | `✅ FILLED: {side} {qty} {ticker} @ ${price}` |
| Position closed | `💰 CLOSED: {ticker} | {exit_reason} | P&L: ${pnl} ({pnl_pct}%)` |
| Daily summary | `📊 Bot run OK | {n_signals} signals | {n_orders} orders | {n_open} open` |
| Error | `🚨 ERROR in {function}: {exception}` |

---

## 10. Technical Stack

| Component | Choice |
|---|---|
| Language | Python 3.11+ |
| Broker SDK | `alpaca-py` (official Alpaca SDK) |
| Indicators | `pandas-ta` or compute MACD manually with `pandas` |
| Storage | SQLite (stdlib `sqlite3`) |
| Notifications | `requests` → Slack incoming webhook |
| Scheduling | cron (host-level) |
| Secrets | `.env` file + `python-dotenv` (never committed) |
| Host | Single always-on machine (Raspberry Pi, droplet, or local dev box) |

### Required environment variables
```
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ALPACA_BASE_URL=https://paper-api.alpaca.markets
SLACK_WEBHOOK_URL=
```

---

## 11. Out of Scope for v1

Explicitly **not** building:
- DCF / fundamental screening
- AI-assisted analysis (Claude API integration)
- Intraday signals or execution
- Shorting
- Options
- TradingView webhooks
- AWS Lambda or any cloud orchestration
- Backtesting framework
- Web dashboard
- Sector concentration caps
- Volatility-adjusted position sizing
- Trailing stops
- Multiple strategies

These are deferred until v1 has run for 60+ trading days and produced data justifying their addition.

---

## 12. Success Criteria for v1

After 60 trading days of paper running, the bot is successful if:

1. **Uptime:** Bot ran on every scheduled trading day with no manual intervention.
2. **Integrity:** Every signal in the log has a corresponding action (order placed, or logged skip with reason).
3. **Reconciliation:** SQLite position table matches Alpaca's position list at end of evaluation period.
4. **Observability:** Daily Slack summaries received; errors surfaced within the same trading day.
5. **Analyzability:** Position table has enough closed trades (target: ≥30) to evaluate strategy behavior by sector, exit reason, and holding period.

Strategy P&L is **not** a success criterion for v1. The goal is a working system, not a profitable one. Profitability evaluation begins in v1.5.

---

## 13. Open Questions for v1.5

To revisit after 60-day evaluation, informed by logged data:

- Is universe size of 75 correct, or should it expand/contract?
- Does alphabetical tiebreaker leave good signals on the table?
- Do commodity ETFs need different position sizing or exit rules?
- Is the 8%/20% stop/target ratio appropriate, or is one leg dominating exits?
- Should sector concentration caps be added?
- What's the cleanest path to layering in a fundamental screen or AI overlay?
