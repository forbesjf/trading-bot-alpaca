"""Tests for the MACD computation in signals.py against STRATEGY.md §3.

The MACD math is verified against an independent pure-Python implementation of
the EMA recursion (not pandas, not pandas-ta) so we are not trusting the
library's EWM blindly, per CLAUDE.md.
"""

import math

import numpy as np
import pandas as pd
import pytest

from signals import FAST, SIGNAL, SLOW, compute_macd

MACD_VALID_FROM = SLOW - 1          # 25: first bar with a valid MACD line
SIGNAL_VALID_FROM = SLOW + SIGNAL - 2  # 33: first bar with a valid signal line


def _ema(values: list[float], span: int) -> list[float]:
    """EMA with adjust=False semantics, seeded at the first value."""
    alpha = 2.0 / (span + 1)
    out: list[float] = []
    prev: float | None = None
    for x in values:
        prev = x if prev is None else alpha * x + (1 - alpha) * prev
        out.append(prev)
    return out


def _reference_macd(closes: list[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Hand-rolled MACD/signal/histogram, independent of pandas."""
    ema_fast = _ema(closes, FAST)
    ema_slow = _ema(closes, SLOW)
    macd = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal = _ema(macd, SIGNAL)
    hist = [m - s for m, s in zip(macd, signal)]
    return np.array(macd), np.array(signal), np.array(hist)


def _df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def test_macd_values_match_hand_calculation() -> None:
    """MACD/signal/histogram match an independent recursion over a known series."""
    closes = [100 + 10 * math.sin(i / 5.0) + 0.2 * i for i in range(60)]
    result = compute_macd(_df(closes))
    ref_macd, ref_signal, ref_hist = _reference_macd(closes)

    warm = slice(SIGNAL_VALID_FROM, None)
    np.testing.assert_allclose(result["macd"].to_numpy()[warm], ref_macd[warm], atol=1e-9)
    np.testing.assert_allclose(result["signal"].to_numpy()[warm], ref_signal[warm], atol=1e-9)
    np.testing.assert_allclose(result["histogram"].to_numpy()[warm], ref_hist[warm], atol=1e-9)

    # A flat price series yields exactly zero MACD/signal/histogram once warmed.
    flat = compute_macd(_df([50.0] * 60))
    assert flat["macd"].iloc[-1] == pytest.approx(0.0, abs=1e-12)
    assert flat["signal"].iloc[-1] == pytest.approx(0.0, abs=1e-12)
    assert flat["histogram"].iloc[-1] == pytest.approx(0.0, abs=1e-12)


def test_detects_bullish_crossover() -> None:
    """A downtrend reversing into an uptrend produces a bullish crossover."""
    closes = [100 - 0.5 * i for i in range(40)] + [80 + 1.0 * i for i in range(40)]
    result = compute_macd(_df(closes))
    hist = result["histogram"].to_numpy()
    idx = np.where(result["bullish_crossover"].to_numpy())[0]

    assert idx.size >= 1, "expected at least one bullish crossover"
    for i in idx:
        assert i >= SIGNAL_VALID_FROM            # only in the warmed region
        assert hist[i] > 0 and hist[i - 1] <= 0  # histogram actually crossed up
    assert idx.min() >= 40                        # after the bar-40 reversal
    # No bar is flagged as both bullish and bearish.
    assert not result["bearish_crossover"].to_numpy()[idx].any()


def test_detects_bearish_crossover() -> None:
    """An uptrend reversing into a downtrend produces a bearish crossover."""
    closes = [80 + 1.0 * i for i in range(40)] + [120 - 0.8 * i for i in range(40)]
    result = compute_macd(_df(closes))
    hist = result["histogram"].to_numpy()
    idx = np.where(result["bearish_crossover"].to_numpy())[0]

    assert idx.size >= 1, "expected at least one bearish crossover"
    for i in idx:
        assert i >= SIGNAL_VALID_FROM
        assert hist[i] < 0 and hist[i - 1] >= 0  # histogram actually crossed down
    assert idx.min() >= 40
    assert not result["bullish_crossover"].to_numpy()[idx].any()


def test_returns_nan_for_insufficient_data() -> None:
    """Too few bars yields NaN indicator values and no crossover flags."""
    # Fewer than SLOW bars: the MACD line cannot be computed at all.
    short = compute_macd(_df([100.0 + i for i in range(10)]))
    assert short["macd"].isna().all()
    assert short["signal"].isna().all()
    assert short["histogram"].isna().all()
    assert not short["bullish_crossover"].any()
    assert not short["bearish_crossover"].any()

    # Between SLOW and the signal warmup: MACD has values but the signal line
    # (and therefore the histogram) is still entirely NaN.
    mid = compute_macd(_df([100.0 + math.sin(i) for i in range(30)]))
    assert mid["macd"].iloc[:MACD_VALID_FROM].isna().all()
    assert mid["macd"].iloc[MACD_VALID_FROM:].notna().all()
    assert mid["signal"].isna().all()
    assert mid["histogram"].isna().all()
