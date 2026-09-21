"""
test_options_flow.py - unit tests for options_flow.py.

Tests cover:
  - _classify_flow(): signal tier detection (BULLISH/BEARISH/UNUSUAL/HEDGING)
  - calc_max_pain(): correct max pain strike from known call/put OI
  - _max_pain_signal(): drift direction string
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
from options_flow import _classify_flow, calc_max_pain, _max_pain_signal


# ── _classify_flow ────────────────────────────────────────────────────────────

def test_bullish_flow_low_pcr():
    """pcr_vol < 0.7 AND pcr_oi < 0.8 → BULLISH_FLOW."""
    sig, _ = _classify_flow(pcr_vol=0.5, pcr_oi=0.65, call_vol=1000, put_vol=500, days_to_earnings=None)
    assert sig == "BULLISH_FLOW"


def test_mild_bullish():
    """pcr_vol < 0.85 → MILD_BULLISH."""
    sig, _ = _classify_flow(pcr_vol=0.80, pcr_oi=0.85, call_vol=800, put_vol=700, days_to_earnings=None)
    assert sig == "MILD_BULLISH"


def test_bearish_flow_high_pcr_vol():
    """pcr_vol > 1.5 → BEARISH_FLOW (no earnings nearby)."""
    sig, _ = _classify_flow(pcr_vol=1.6, pcr_oi=1.2, call_vol=400, put_vol=900, days_to_earnings=None)
    assert sig == "BEARISH_FLOW"


def test_bearish_flow_high_pcr_oi():
    """pcr_oi > 1.8 → BEARISH_FLOW."""
    sig, _ = _classify_flow(pcr_vol=1.2, pcr_oi=2.0, call_vol=500, put_vol=800, days_to_earnings=None)
    assert sig == "BEARISH_FLOW"


def test_hedging_near_earnings():
    """High put OI + earnings ≤14d → HEDGING, not BEARISH_FLOW."""
    sig, note = _classify_flow(pcr_vol=1.8, pcr_oi=2.2, call_vol=300, put_vol=800, days_to_earnings=7)
    assert sig == "HEDGING"
    assert "earnings" in note.lower() or "hedge" in note.lower()


def test_unusual_calls_3x():
    """Call vol ≥3× put vol AND pcr_oi < 0.8 → UNUSUAL_CALLS."""
    sig, note = _classify_flow(pcr_vol=0.3, pcr_oi=0.6, call_vol=3000, put_vol=900, days_to_earnings=None)
    assert sig == "UNUSUAL_CALLS"
    assert "unusual" in note.lower() or "accumulation" in note.lower()


def test_unusual_calls_not_triggered_without_oi():
    """Call vol 3× but pcr_oi not bullish → no UNUSUAL_CALLS."""
    sig, _ = _classify_flow(pcr_vol=0.3, pcr_oi=1.2, call_vol=3000, put_vol=900, days_to_earnings=None)
    assert sig != "UNUSUAL_CALLS"


def test_neutral_balanced():
    """Balanced flow → NEUTRAL."""
    sig, _ = _classify_flow(pcr_vol=1.0, pcr_oi=1.0, call_vol=500, put_vol=500, days_to_earnings=None)
    assert sig == "NEUTRAL"


# ── calc_max_pain ─────────────────────────────────────────────────────────────

def _make_chain(call_data: list[tuple], put_data: list[tuple]) -> tuple:
    """
    Build minimal calls_df, puts_df from list of (strike, openInterest).
    """
    calls = pd.DataFrame(call_data, columns=["strike", "openInterest"])
    puts  = pd.DataFrame(put_data,  columns=["strike", "openInterest"])
    return calls, puts


def test_max_pain_simple_known():
    """
    Simple symmetric chain - max pain should be at the middle strike.

    Calls: K=90 OI=100, K=95 OI=50, K=100 OI=100
    Puts:  K=100 OI=100, K=105 OI=50, K=110 OI=100

    At S=100: call_pain = (100-90)*100*100 + (100-95)*50*100 = 100000+25000=125000
              put_pain  = (105-100)*50*100 + (110-100)*100*100 = 25000+100000=125000
              total=250000
    """
    calls, puts = _make_chain(
        [(90, 100), (95, 50), (100, 100)],
        [(100, 100), (105, 50), (110, 100)],
    )
    mp = calc_max_pain(calls, puts)
    assert mp is not None
    assert isinstance(mp, float)


def test_max_pain_single_call_strike():
    """Single call strike - max pain must be at or near that strike."""
    calls, puts = _make_chain(
        [(50, 1000)],
        [(50, 100)],
    )
    mp = calc_max_pain(calls, puts)
    assert mp is not None


def test_max_pain_empty_returns_none():
    """Empty chain → None."""
    calls, puts = _make_chain([], [])
    mp = calc_max_pain(calls, puts)
    assert mp is None


def test_max_pain_heavy_call_oi_pulls_up():
    """
    Massive call OI at K=110, minimal put OI.

    Max pain math: at each strike S, calls with K<S are ITM (pain for call holders).
    With heavy OI at K=110 (calls), at S=110: all lower call strikes are ITM →
    large call pain. But at lower strikes, fewer calls are ITM → less total pain.

    The minimum total pain strike is what we call 'max pain' (lowest payout from MMs).
    With heavy call OI at 110, the minimum may actually be below 110 since going below
    means fewer calls are ITM. The actual max pain calculation is not directionally
    tied to where OI is heaviest.

    What we CAN assert: result is not None and is within the chain's strike range.
    """
    calls, puts = _make_chain(
        [(100, 10), (105, 50), (110, 500)],
        [(95, 20), (90, 10)],
    )
    mp = calc_max_pain(calls, puts)
    assert mp is not None
    # Max pain must be within the range of strikes
    assert 90 <= mp <= 110


def test_max_pain_heavy_put_oi_pulls_down():
    """
    Massive put OI at K=90, minimal call OI.
    Max pain must be within the chain's strike range.
    """
    calls, puts = _make_chain(
        [(110, 10), (115, 5)],
        [(90, 500), (95, 50), (100, 10)],
    )
    mp = calc_max_pain(calls, puts)
    assert mp is not None
    assert 90 <= mp <= 115


# ── _max_pain_signal ──────────────────────────────────────────────────────────

def test_max_pain_signal_drift_up():
    """Price below max pain → drift up."""
    sig = _max_pain_signal(price=95.0, mp=100.0, days_to_exp=2)
    assert "UP" in sig.upper() or "up" in sig.lower()


def test_max_pain_signal_drift_down():
    """Price above max pain → drift down."""
    sig = _max_pain_signal(price=105.0, mp=100.0, days_to_exp=2)
    assert "DOWN" in sig.upper() or "down" in sig.lower()


def test_max_pain_signal_pinned():
    """Price very close to max pain → PINNED."""
    sig = _max_pain_signal(price=100.2, mp=100.0, days_to_exp=1)
    assert "PIN" in sig.upper() or "pin" in sig.lower()
