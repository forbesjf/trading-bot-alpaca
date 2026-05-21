"""MACD signal computation for the trading bot.

Implements the standard MACD indicator from STRATEGY.md §3 on daily closes:
fast EMA 12, slow EMA 26, signal EMA 9, all with ``adjust=False`` (the
recursive form ``y_t = alpha*x_t + (1-alpha)*y_{t-1}`` seeded at the first
close). This module is pure computation — no I/O, no Alpaca, no DB — so the
math can be unit-tested in isolation.
"""

import pandas as pd

FAST: int = 12
SLOW: int = 26
SIGNAL: int = 9


def compute_macd(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute MACD (12/26/9) and crossover flags from a bar DataFrame.

    Args:
        bars: DataFrame indexed by bar, containing at least a ``close`` column.

    Returns:
        A DataFrame aligned to ``bars.index`` with columns:
          - ``macd``: MACD line (fast EMA − slow EMA)
          - ``signal``: signal line (EMA of the MACD line)
          - ``histogram``: ``macd − signal``
          - ``bullish_crossover``: True where MACD crosses above signal
          - ``bearish_crossover``: True where MACD crosses below signal

        During the warmup period the indicator is not yet reliable, so values
        are NaN: the MACD line until ``SLOW`` bars exist, and the signal line
        (and histogram) until an additional ``SIGNAL - 1`` bars exist. Where
        the histogram is NaN, both crossover flags are False.

    Raises:
        KeyError: if ``bars`` has no ``close`` column.
    """
    if "close" not in bars.columns:
        raise KeyError("bars must contain a 'close' column")

    close = bars["close"].astype("float64")

    ema_fast = close.ewm(span=FAST, adjust=False).mean()
    ema_slow = close.ewm(span=SLOW, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=SIGNAL, adjust=False).mean()

    # Mask the warmup region. The MACD line needs SLOW observations; the signal
    # line is an EMA of the MACD line, so it needs SIGNAL - 1 more on top.
    macd.iloc[: SLOW - 1] = float("nan")
    signal.iloc[: SLOW + SIGNAL - 2] = float("nan")
    histogram = macd - signal  # NaN wherever macd or signal is NaN

    # A bullish crossover is the bar where the histogram turns from <=0 to >0
    # (MACD crossing above signal); bearish is the mirror. NaN comparisons are
    # False, so the warmup region produces no spurious crossovers.
    prev = histogram.shift(1)
    bullish = (histogram > 0) & (prev <= 0)
    bearish = (histogram < 0) & (prev >= 0)

    return pd.DataFrame(
        {
            "macd": macd,
            "signal": signal,
            "histogram": histogram,
            "bullish_crossover": bullish,
            "bearish_crossover": bearish,
        },
        index=bars.index,
    )
