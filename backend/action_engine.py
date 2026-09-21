"""
action_engine.py - Action item generators (v2 + v3 synthesis engines).

The brains of the morning briefing. Combines score + RSI + insider +
options flow + news sentiment + pattern + earnings + position-type rules
into prioritized action items per position.

v2: Original engine. Score + RSI + position-type rules.
v3: Full 6-signal synthesis. Adds insider, options flow, max pain,
    gamma walls, news sentiment, macro pulse.

Output schema: list of dicts with keys
  {num, priority, ticker, account, verb, detail, color, signals}

Priority order: URGENT > ACTION > WATCH > INFO

`POSITION_MACRO` map lives in morning_run.py (caller-supplied via param)
or imported lazily from score.py's TICKER_NARRATIVES inside v3.
"""
from __future__ import annotations

from user_config import rule as _rule


_PRIO_ORDER = {"URGENT": 0, "ACTION": 1, "WATCH": 2, "INFO": 3}


def generate_action_items_v2(
    data: dict,
    snapshots: dict,
    pattern_results: dict | None,
    market_snaps: dict | None,
    div_info: dict | None,
) -> list[dict]:
    """
    Returns numbered, prioritized trade recommendations.
    Each item: {num, priority, ticker, account, verb, detail, color}
    """
    items: list[dict] = []
    pr = pattern_results or {}
    ms = market_snaps or {}

    vix      = (ms.get("^VIX") or {}).get("price") or 15.0
    spy_rsi  = (ms.get("SPY")  or {}).get("rsi")   or 50.0
    qqq_rsi  = (ms.get("QQQ")  or {}).get("rsi")   or 50.0

    def add(priority, ticker, account, verb, detail, color):
        items.append({"priority": priority, "ticker": ticker, "account": account,
                      "verb": verb, "detail": detail, "color": color})

    # ── Market-wide ───────────────────────────────────────────────────────
    if vix > 35:
        add("URGENT", "MARKET", "ALL", "REDUCE SIZING 50%",
            f"VIX {vix:.1f} - extreme fear. Cut all new entry sizes in half. No lump-sum today.", "red")
    elif vix > 25:
        add("WATCH", "MARKET", "ALL", "REDUCE SIZING 25%",
            f"VIX {vix:.1f} - elevated. Use 75% of standard position size on new entries.", "orange")

    if spy_rsi > 75:
        add("WATCH", "MARKET", "ALL", "OVERBOUGHT - NO NEW LUMP-SUM",
            f"SPY RSI {spy_rsi:.1f} - wait for pullback before adding new positions.", "orange")
    elif spy_rsi < 35:
        add("ACTION", "MARKET", "ALL", "OVERSOLD - BUY AGGRESSIVELY",
            f"SPY RSI {spy_rsi:.1f} - best entry environment. Deploy cash into scored setups.", "green")

    if qqq_rsi > 75:
        add("WATCH", "MARKET", "ALL", "TECH OVERBOUGHT",
            f"QQQ RSI {qqq_rsi:.1f} - be selective on new tech/AI entries.", "orange")

    # ── Per-position ──────────────────────────────────────────────────────
    for acct_name, acct in data["accounts"].items():
        for pos in acct.get("positions", []):
            t      = pos["ticker"]
            snap   = snapshots.get(t, {})
            price  = snap.get("price") or pos["avg_cost"]
            avg    = pos["avg_cost"]
            shares = pos["shares"]
            pct    = ((price - avg) / avg) * 100
            ptype  = pos.get("type", "")
            stop   = pos.get("stop")
            rsi      = snap.get("rsi")
            dte      = snap.get("days_to_earnings")
            pat_data = pr.get(t, {})  # dict with chart_pattern, trend, rsi_divergence keys
            chart_pat = pat_data.get("chart_pattern", {}) if isinstance(pat_data, dict) else {}
            rsi_div   = pat_data.get("rsi_divergence", {}) if isinstance(pat_data, dict) else {}

            # Earnings disqualifier
            if dte is not None and 0 <= dte <= _rule("earnings_blackout_days"):
                if dte <= 3:
                    add("URGENT", t, acct_name, f"EARNINGS IN {dte}D - DISQUALIFIER",
                        f"Do NOT open new {t} position. Existing: hold or decide before earnings if nervous.", "red")
                else:
                    add("ACTION", t, acct_name, f"EARNINGS IN {dte}D - DISQUALIFIER",
                        f"Do NOT add new {t} shares. Hold existing position through earnings.", "orange")

            # Stop proximity (any type with a stop)
            if stop and price > stop:
                gap_pct = ((price - stop) / price) * 100
                if gap_pct < 5:
                    add("URGENT", t, acct_name, "STOP IMMINENT",
                        f"Price ${price:.2f} - GTC stop ${stop:.2f} - only {gap_pct:.1f}% away. Verify order active in Fidelity.", "red")
                elif gap_pct < 10:
                    add("WATCH", t, acct_name, "STOP NEAR",
                        f"Price ${price:.2f} - GTC stop ${stop:.2f} - {gap_pct:.1f}% buffer. Monitor.", "orange")

            # Type S - Swing exit ladder
            if ptype == "S":
                if pct >= 20:
                    gain = (price - avg) * shares
                    add("ACTION", t, acct_name, f"SELL ALL {shares}sh @ ~${price:.2f}",
                        f"+{pct:.1f}% - Swing +20% TARGET. Sell all {shares} shares at market. Est total gain: +${gain:.0f}.", "green")
                elif pct >= 15:
                    sell_sh = max(1, round(shares * 0.75))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"SELL 75% ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% - Sell {sell_sh} of {shares} shares. Keep {shares - sell_sh}sh. Move stop to breakeven ${avg:.2f}. Gain: +${gain:.0f}.", "green")
                elif pct >= 10:
                    sell_sh = max(1, round(shares * 0.5))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"SELL 50% ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% - Sell {sell_sh} of {shares} shares at market. Move GTC stop to breakeven ${avg:.2f}. Gain: +${gain:.0f}.", "green")
                elif pct >= 5:
                    add("WATCH", t, acct_name, f"MOVE STOP TO BREAKEVEN ${avg:.2f}",
                        f"+{pct:.1f}% - Log into Fidelity and move GTC stop from ${stop or 0:.2f} to ${avg:.2f}.", "blue")
                elif pct <= -8:
                    add("URGENT", t, acct_name, "SWING STOP BREACHED",
                        f"{pct:.1f}% - below −8% stop. Verify GTC executed in Fidelity. If not, exit at market now.", "red")

            # Type L - Long exit/add ladder
            elif ptype == "L":
                if pct >= 50:
                    sell_sh = max(1, round(shares * 0.25))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"SELL 25% MORE ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% - Long +50% level. Sell {sell_sh} additional shares. Reassess thesis. Gain on sale: +${gain:.0f}.", "green")
                elif pct >= 30:
                    sell_sh = max(1, round(shares * 0.5))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"SELL 50% ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% - Long profit ladder. Sell {sell_sh} of {shares} shares at market. Gain: +${gain:.0f}. Hold rest.", "green")
                elif pct >= 15:
                    sell_sh = max(1, round(shares * 0.25))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"SELL 25% ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% - Long profit ladder. Sell {sell_sh} of {shares} shares at market. Gain: +${gain:.0f}. Hold rest.", "green")
                elif -15 <= pct <= -8:
                    earn_ok = (dte is None or dte > _rule("earnings_blackout_days"))
                    if earn_ok:
                        add("WATCH", t, acct_name, "ADD ZONE (−8% to −15%)",
                            f"{pct:.1f}% - Type L rule: NOT an exit. Consider adding if thesis intact. Run score.py first.", "blue")
                elif pct < -15:
                    add("URGENT", t, acct_name, "DISASTER STOP ZONE",
                        f"{pct:.1f}% - below −15%. Exit ONLY if thesis is broken - NOT a price-only exit. Check fundamentals.", "red")

            # Type I - Income
            elif ptype == "I":
                if pct < -20:
                    add("WATCH", t, acct_name, "INCOME: CHECK DISTRIBUTION",
                        f"{pct:.1f}% - significantly underwater. Verify distribution is still intact. Not an exit on price alone.", "orange")

            # Spec rules
            elif ptype == "Spec":
                if t == "BBAI" and price < 2.50:
                    add("URGENT", t, acct_name, "EXIT SPEC - BELOW FLOOR",
                        f"${price:.2f} below $2.50 floor. Exit immediately per spec rules. Do not average down.", "red")
                elif pct <= -30:
                    add("WATCH", t, acct_name, "SPEC: CHECK THESIS",
                        f"{pct:.1f}% - any contract cancellations? If thesis broken, exit. Never add to losing spec.", "orange")

            # Bearish chart pattern alert (non-Lifetime only)
            if ptype not in ("Lifetime",):
                cp_sig  = chart_pat.get("signal")
                cp_conf = chart_pat.get("confidence", 0)
                cp_name = chart_pat.get("pattern", "")
                if cp_sig == "bearish" and cp_conf >= 0.65 and cp_name:
                    pname = cp_name.replace("_", " ").title()
                    add("WATCH", t, acct_name, f"BEARISH PATTERN: {pname.upper()}",
                        f"{cp_conf:.0%} confidence - tighten stop or consider reducing before pattern confirms.", "orange")

            # Bullish RSI divergence on L positions
            if ptype == "L" and rsi:
                div_type = rsi_div.get("divergence")
                if div_type == "bullish" and -15 <= pct <= 0:
                    add("WATCH", t, acct_name, "BULLISH RSI DIVERGENCE",
                        f"RSI {rsi:.0f} diverging bullish while price {pct:.1f}%. Potential reversal. Add zone if thesis intact.", "blue")

        # Pending orders proximity
        for pos in acct.get("positions", []):
            t     = pos["ticker"]
            price = (snapshots.get(t) or {}).get("price") or pos["avg_cost"]
            for order in pos.get("pending_orders", []):
                if order.get("status") != "open":
                    continue
                op       = order.get("order", "")
                op_price = order.get("price", 0)
                op_sh    = order.get("shares", 0)
                note     = order.get("note", "")
                if not op_price:
                    continue
                gap_pct = abs(price - op_price) / price * 100
                suffix  = f" - {note}" if note else ""
                if gap_pct <= 1:
                    add("URGENT", t, acct_name, f"ORDER FILLING NOW",
                        f"{'BUY' if op=='buy' else 'SELL'} {op_sh}sh limit @${op_price:.2f} | Current ${price:.2f} | {gap_pct:.1f}% gap. Check Fidelity!{suffix}", "green" if op == "buy" else "orange")
                elif gap_pct <= 3:
                    add("ACTION", t, acct_name, f"ORDER VERY NEAR",
                        f"{'BUY' if op=='buy' else 'SELL'} {op_sh}sh @${op_price:.2f} | Current ${price:.2f} | {gap_pct:.1f}% gap. Watch closely.{suffix}", "blue")
                elif gap_pct <= 8:
                    add("WATCH", t, acct_name, f"PENDING ORDER",
                        f"{'BUY' if op=='buy' else 'SELL'} {op_sh}sh @${op_price:.2f} | Current ${price:.2f} | {gap_pct:.1f}% away.{suffix}", "blue")

        # Watchlist orders
        for wl in acct.get("watchlist_orders", []):
            t        = wl["ticker"]
            price    = (snapshots.get(t) or {}).get("price")
            op_price = wl.get("price", 0)
            if price and op_price:
                gap_pct = abs(price - op_price) / price * 100
                if gap_pct <= 5:
                    stop_str = f" | Stop if fills: ${wl.get('stop_if_fills', 0):.2f}" if wl.get("stop_if_fills") else ""
                    add("WATCH", t, acct_name, "WATCHLIST ORDER NEAR",
                        f"BUY @${op_price:.2f} | Current ${price:.2f} | {gap_pct:.1f}% gap{stop_str} | {wl.get('thesis', '')}", "blue")

    # Sort and number
    items.sort(key=lambda x: _PRIO_ORDER.get(x.get("priority", "INFO"), 3))
    for i, item in enumerate(items, 1):
        item["num"] = i
    return items


def generate_action_items_v3(
    data: dict,
    snapshots: dict,
    pattern_results: dict | None,
    market_snaps: dict | None,
    div_info: dict | None,
    insider_signals: dict | None = None,
    options_flows: dict | None = None,
    ticker_news: dict | None = None,
    macro_results: dict | None = None,
) -> list[dict]:
    """
    v3: Full 6-signal synthesis engine.
    Combines score + RSI + insider + options flow + max pain + news sentiment
    into ONE specific action per position: verb, quantity, price, reason.

    Signals used:
      1. 180pt entry score    - is this worth holding/adding?
      2. RSI                  - oversold/overbought threshold
      3. Insider buying       - STRONG/CLUSTER = hold conviction through dips
      4. Options P/C flow     - BULLISH_FLOW / UNUSUAL_CALLS = momentum
      5. Max pain             - where price going THIS WEEK, specific target
      6. Gamma walls          - exact entry/exit limit prices
      7. Pattern detection    - bearish = tighten, bullish = add zone
      8. Earnings DTE         - hard disqualifier window
      9. Position type rules  - S/L/I/Spec/Lifetime exits unchanged
     10. News sentiment       - THESIS NEGATIVE blocks ADD, POSITIVE boosts conviction
     11. Macro pulse          - SILENT = thesis cooling flag

    Each item: {num, priority, ticker, account, verb, detail, color, signals}
    """
    from score import score_ticker, size_position, TICKER_NARRATIVES as _NS_TICKER_NARRATIVES
    from news_sentiment import classify_ticker_news, classify_macro_pulse, explain_big_mover
    from spec_score import is_spec_candidate, score_spec

    items: list[dict] = []
    pr   = pattern_results or {}
    ms   = market_snaps or {}
    ins  = insider_signals or {}
    opt  = options_flows or {}
    tnws = ticker_news or {}
    mres = macro_results or {}

    vix     = (ms.get("^VIX") or {}).get("price") or 15.0
    spy_rsi = (ms.get("SPY")  or {}).get("rsi")   or 50.0
    qqq_rsi = (ms.get("QQQ")  or {}).get("rsi")   or 50.0

    def add(priority, ticker, account, verb, detail, color, signals=""):
        items.append({
            "priority": priority, "ticker": ticker, "account": account,
            "verb": verb, "detail": detail, "color": color, "signals": signals,
        })

    # ── Market-wide (same as v2) ──────────────────────────────────────────────
    if vix > 35:
        add("URGENT", "MARKET", "ALL", "REDUCE SIZING 50%",
            f"VIX {vix:.1f} - extreme fear. Cut all new entries in half.", "red", "VIX")
    elif vix > 25:
        add("WATCH", "MARKET", "ALL", "REDUCE SIZING 25%",
            f"VIX {vix:.1f} - elevated. Use 75% of standard size.", "orange", "VIX")
    if spy_rsi > 75:
        add("WATCH", "MARKET", "ALL", "OVERBOUGHT - NO NEW LUMP-SUM",
            f"SPY RSI {spy_rsi:.1f} - wait for pullback.", "orange", "SPY RSI")
    elif spy_rsi < 35:
        add("ACTION", "MARKET", "ALL", "OVERSOLD - BUY AGGRESSIVELY",
            f"SPY RSI {spy_rsi:.1f} - best entry environment.", "green", "SPY RSI")

    # ── Per-position ──────────────────────────────────────────────────────────
    for acct_name, acct in data["accounts"].items():
        cash = acct.get("cash", 0)

        for pos in acct.get("positions", []):
            t      = pos["ticker"]
            snap   = snapshots.get(t, {})
            price  = snap.get("price") or pos["avg_cost"]
            avg    = pos["avg_cost"]
            shares = pos["shares"]
            pct    = ((price - avg) / avg) * 100
            ptype  = pos.get("type", "")
            stop   = pos.get("stop")
            rsi    = snap.get("rsi")
            dte    = snap.get("days_to_earnings")

            # Pattern data
            pat_data  = pr.get(t, {}) if isinstance(pr.get(t), dict) else {}
            chart_pat = pat_data.get("chart_pattern", {})
            rsi_div   = pat_data.get("rsi_divergence", {})
            cp_sig    = chart_pat.get("signal", "")
            cp_conf   = chart_pat.get("confidence", 0)

            # Insider signal
            ins_data   = ins.get(t, {})
            ins_signal = ins_data.get("signal", "NONE")
            ins_desc   = ins_data.get("description", "")
            has_insider = ins_signal in ("STRONG", "CLUSTER", "NOTABLE")

            # Options flow + max pain
            flow        = opt.get(t, {})
            opt_signal  = flow.get("signal", "NEUTRAL")
            mp          = flow.get("max_pain")
            mp_dist     = flow.get("max_pain_dist_pct")  # + = price below mp (drift up), - = above (drift down)
            mp_days     = flow.get("max_pain_days")
            mp_sig_str  = flow.get("max_pain_signal", "")
            pcr_vol     = flow.get("pcr_vol")

            # Gamma walls (nearest above/below)
            key_strikes = flow.get("key_strikes", [])
            relevant    = [s for s in key_strikes[:8] if abs(s["dist_pct"]) <= 20]
            wall_above  = min((s for s in relevant if s["dist_pct"] > 0.5),
                              key=lambda x: x["dist_pct"], default=None)
            wall_below  = max((s for s in relevant if s["dist_pct"] < -0.5),
                              key=lambda x: x["dist_pct"], default=None)

            # News + macro signals
            headlines      = tnws.get(t, [])
            pos_narratives = _NS_TICKER_NARRATIVES.get(t, [])
            news_result    = classify_ticker_news(headlines, t, pos_narratives)
            news_sig       = news_result["signal"]        # POSITIVE / NEGATIVE / NEUTRAL
            news_str_val   = news_result["strength"]      # THESIS / MODERATE / WEAK
            news_thesis    = news_result["thesis_news"]   # bool
            news_trigger   = news_result["trigger"]       # headline snippet
            news_summary   = news_result["summary"]

            macro_result   = classify_macro_pulse(t, pos_narratives, mres)
            macro_pulse    = macro_result["pulse"]        # STRONG / ACTIVE / SILENT / NEUTRAL
            macro_silent   = macro_result["silent_narratives"]
            macro_active   = macro_result["active_narratives"]

            # Score (run without network - uses already-fetched snap)
            try:
                insider_buy_flag = has_insider
                score_result = score_ticker(snap, insider_buy=insider_buy_flag)
                score_pts    = score_result.total
                disqualified = score_result.disqualified
                disq_reason  = score_result.disqualify_reason
            except Exception:
                score_pts    = 0
                disqualified = False
                disq_reason  = ""

            # Build signal summary string for display
            sig_parts = []
            if score_pts:       sig_parts.append(f"Score {score_pts}/180")
            if rsi:             sig_parts.append(f"RSI {rsi:.0f}")
            if has_insider:     sig_parts.append(f"Insider {ins_signal}")
            if opt_signal not in ("NEUTRAL", "ERROR", "NO_OPTIONS", "NO_DATA"):
                sig_parts.append(f"Flow {opt_signal}")
            if mp and mp_dist is not None:
                sig_parts.append(f"MP${mp:.0f}({mp_dist:+.0f}%)")
            if news_sig != "NEUTRAL":
                sig_parts.append(f"News {news_sig}/{news_str_val}")
            if macro_pulse in ("STRONG", "ACTIVE"):
                sig_parts.append(f"Macro {macro_pulse}")
            elif macro_pulse == "SILENT" and pos_narratives:
                sig_parts.append("Macro SILENT")
            signals_str = " | ".join(sig_parts)

            # ── HARD DISQUALIFIERS (same as v2, check first) ─────────────────

            # Earnings disqualifier
            if dte is not None and 0 <= dte <= _rule("earnings_blackout_days"):
                urgency = "URGENT" if dte <= 3 else "ACTION"
                color   = "red"    if dte <= 3 else "orange"
                # Max pain context for earnings tickers
                mp_context = f" Max pain ${mp:.0f} ({mp_dist:+.1f}%)." if mp and mp_dist else ""
                add(urgency, t, acct_name, f"EARNINGS IN {dte}D - DO NOT ADD",
                    f"Hold existing {shares}sh. No new shares.{mp_context} "
                    f"Pre-earnings decision required.",
                    color, signals_str)

            # Stop imminent
            if stop and price > stop:
                gap_pct = ((price - stop) / price) * 100
                # Check if put wall provides floor before stop
                floor_str = f" Put wall ${wall_below['strike']:.0f} may provide floor first." if wall_below else ""
                if gap_pct < 5:
                    add("URGENT", t, acct_name, "STOP IMMINENT - VERIFY FIDELITY",
                        f"Price ${price:.2f} | Stop ${stop:.2f} | {gap_pct:.1f}% gap.{floor_str}",
                        "red", signals_str)
                elif gap_pct < 10:
                    add("WATCH", t, acct_name, "STOP NEAR",
                        f"Price ${price:.2f} | Stop ${stop:.2f} | {gap_pct:.1f}% buffer.{floor_str}",
                        "orange", signals_str)

            # ── NEWS SENTIMENT ALERTS ─────────────────────────────────────────
            # Thesis-level NEGATIVE news → URGENT flag (block all adds)
            if news_sig == "NEGATIVE" and news_str_val == "THESIS":
                add("URGENT", t, acct_name, "THESIS RISK - NEWS NEGATIVE",
                    f"⚠️ {news_summary} | Trigger: '{news_trigger[:80]}' "
                    f"DO NOT ADD. Verify position thesis is still intact.",
                    "red", signals_str)
            # Thesis-level POSITIVE news → ACTION flag (boost conviction)
            elif news_sig == "POSITIVE" and news_str_val == "THESIS" and ptype not in ("Spec",):
                add("ACTION", t, acct_name, "CATALYST NEWS - THESIS ACCELERATING",
                    f"✅ {news_summary} | Trigger: '{news_trigger[:80]}'",
                    "green", signals_str)
            # Moderate NEGATIVE on non-Lifetime → WATCH
            elif news_sig == "NEGATIVE" and news_str_val == "MODERATE" and ptype not in ("Lifetime",):
                add("WATCH", t, acct_name, "NEWS HEADWIND - WATCH",
                    f"{news_summary} | '{news_trigger[:80]}'",
                    "orange", signals_str)

            # ── MACRO PULSE ALERT ─────────────────────────────────────────────
            # SILENT macro narrative for thesis-heavy positions → flag cooling
            if macro_pulse == "SILENT" and pos_narratives and ptype in ("L", "I", "S"):
                silent_str = ", ".join(macro_silent).replace("_", " ")
                add("WATCH", t, acct_name, "MACRO CHECK - NARRATIVE QUIET",
                    f"Narrative(s) [{silent_str}] absent from today's news. "
                    f"Thesis cooling? Verify macro tailwind still active before adding.",
                    "orange", signals_str)

            # ── INSIDER OVERRIDE - strong conviction overrides weak signals ───
            # If insider STRONG/CLUSTER AND position is down → hold signal
            if has_insider and pct <= -5 and ptype not in ("Spec",):
                dollar_paid = abs((price - avg) * shares)
                add("WATCH", t, acct_name, "INSIDER SIGNAL - HOLD THROUGH DIP",
                    f"[{ins_signal}] {ins_desc}. "
                    f"Position {pct:.1f}% down (${dollar_paid:.0f}). "
                    f"Insiders see value here. Do NOT exit on price alone.",
                    "blue", signals_str)

            # ── MAX PAIN DRIFT ALERT (expiry ≤3 days, >4% away) ─────────────
            if mp and mp_dist is not None and mp_days is not None:
                if mp_days <= 3 and abs(mp_dist) >= 4:
                    drift_dir = "UP" if mp_dist > 0 else "DOWN"
                    color = "green" if mp_dist > 0 else "orange"
                    # Quantify: how many shares to add/trim if drifting
                    if drift_dir == "UP" and ptype in ("S", "L") and dte is None or (dte or 99) > 15:
                        target_price = wall_above["strike"] if wall_above else mp
                        add("WATCH", t, acct_name,
                            f"MAX PAIN DRIFT UP → ${mp:.0f} this week",
                            f"Price ${price:.2f} | Max pain ${mp:.0f} ({mp_dist:+.1f}%) | "
                            f"Exp {mp_days}d. Mechanical upward pressure. "
                            f"Target: ${target_price:.0f} (gamma wall). HOLD - let max pain pull.",
                            color, signals_str)
                    elif drift_dir == "DOWN" and pct >= 10:
                        trim_sh = max(1, round(shares * 0.25))
                        trim_val = trim_sh * price
                        add("WATCH", t, acct_name,
                            f"MAX PAIN DRIFT DOWN → ${mp:.0f} this week",
                            f"Price ${price:.2f} | Max pain ${mp:.0f} ({mp_dist:+.1f}%) | "
                            f"You're up {pct:.1f}%. Consider trim: sell {trim_sh}sh @ ~${price:.2f} "
                            f"(${trim_val:.0f}) before max pain pulls price down.",
                            "orange", signals_str)

            # ── TYPE S - Swing trades ─────────────────────────────────────────
            if ptype == "S":
                # Exit targets - use gamma wall as target price if available
                target = wall_above["strike"] if wall_above else price * 1.05
                floor  = wall_below["strike"] if wall_below else (stop or price * 0.92)

                if pct >= 20:
                    gain = (price - avg) * shares
                    add("ACTION", t, acct_name, f"SELL ALL {shares}sh @ ~${price:.2f}",
                        f"+{pct:.1f}% - Swing +20% TARGET hit. Sell all {shares}sh at market. "
                        f"Est gain: +${gain:.0f}. " +
                        (f"Next gamma wall ↑${wall_above['strike']:.0f} - already overextended." if wall_above else ""),
                        "green", signals_str)

                elif pct >= 15:
                    sell_sh = max(1, round(shares * 0.75))
                    gain = (price - avg) * sell_sh
                    # Adjust if bullish flow says more upside
                    if opt_signal in ("BULLISH_FLOW", "UNUSUAL_CALLS"):
                        sell_sh = max(1, round(shares * 0.5))  # trim less if momentum strong
                        detail = (f"+{pct:.1f}% | Bullish options flow → trim 50% not 75%. "
                                  f"Sell {sell_sh}sh @ ~${price:.2f} (${gain:.0f}). "
                                  f"Keep {shares-sell_sh}sh. Move stop to breakeven ${avg:.2f}.")
                    else:
                        detail = (f"+{pct:.1f}% | Sell {sell_sh}sh @ ~${price:.2f} (${gain:.0f}). "
                                  f"Keep {shares-sell_sh}sh. Move stop to breakeven ${avg:.2f}. "
                                  f"Next wall ↑${wall_above['strike']:.0f}." if wall_above else
                                  f"+{pct:.1f}% | Sell {sell_sh}sh @ ~${price:.2f}.")
                    add("ACTION", t, acct_name, f"SELL {sell_sh}sh @ ~${price:.2f}", detail, "green", signals_str)

                elif pct >= 10:
                    sell_sh = max(1, round(shares * 0.5))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"SELL 50% ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% | Sell {sell_sh}sh (${gain:.0f}). Move stop to ${avg:.2f}. "
                        f"Next wall ↑${wall_above['strike']:.0f}." if wall_above else
                        f"+{pct:.1f}% | Sell {sell_sh}sh (${gain:.0f}).",
                        "green", signals_str)

                elif pct >= 5:
                    add("WATCH", t, acct_name, f"MOVE STOP TO BREAKEVEN ${avg:.2f}",
                        f"+{pct:.1f}% | Log Fidelity, move GTC stop to ${avg:.2f}. "
                        f"Target: ${target:.0f} (gamma wall). Floor: ${floor:.0f}.",
                        "blue", signals_str)

                elif pct <= -8:
                    add("URGENT", t, acct_name, "SWING STOP BREACHED",
                        f"{pct:.1f}% | Verify GTC executed. If not, EXIT at market now. "
                        f"Put wall ${floor:.0f} may provide bounce - but stop rule overrides.",
                        "red", signals_str)

            # ── TYPE L - Long positions ───────────────────────────────────────
            elif ptype == "L":
                floor  = wall_below["strike"] if wall_below else (stop or avg * 0.85)
                target = wall_above["strike"] if wall_above else price * 1.10

                if pct >= 50:
                    sell_sh = max(1, round(shares * 0.25))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"TRIM 25% ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% | Long +50% level. Trim {sell_sh}sh (${gain:.0f}). "
                        f"Keep {shares-sell_sh}sh - thesis still valid?",
                        "green", signals_str)

                elif pct >= 30:
                    sell_sh = max(1, round(shares * 0.5))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"TRIM 50% ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% | Long profit ladder. Trim {sell_sh}sh (${gain:.0f}). Hold rest.",
                        "green", signals_str)

                elif pct >= 15:
                    sell_sh = max(1, round(shares * 0.25))
                    gain = (price - avg) * sell_sh
                    add("ACTION", t, acct_name, f"TRIM 25% ({sell_sh}sh) @ ~${price:.2f}",
                        f"+{pct:.1f}% | Trim {sell_sh}sh (${gain:.0f}). Hold rest.",
                        "green", signals_str)

                elif -15 <= pct <= -5:
                    earn_ok = dte is None or dte > _rule("earnings_blackout_days")
                    # News BLOCKS add: thesis-level negative = never add
                    news_blocks_add = news_sig == "NEGATIVE" and news_str_val == "THESIS"
                    # ADD ZONE: need score + at least one bullish signal
                    bullish_opts = opt_signal in ("BULLISH_FLOW", "UNUSUAL_CALLS", "MILD_BULLISH")
                    mp_pulling_up = mp_dist is not None and mp_dist > 2
                    rsi_ok = rsi is not None and rsi < 45
                    # Positive news counts as a bullish signal
                    news_bullish = news_sig == "POSITIVE" and news_str_val in ("THESIS", "MODERATE")
                    add_signal_count = sum([bullish_opts, mp_pulling_up, rsi_ok, has_insider, news_bullish])

                    if news_blocks_add:
                        add("WATCH", t, acct_name, "ADD BLOCKED - NEGATIVE NEWS",
                            f"{pct:.1f}% | {news_summary} "
                            f"DO NOT ADD until thesis risk resolved. '{news_trigger[:60]}'",
                            "orange", signals_str)
                    elif earn_ok and add_signal_count >= _rule("min_add_signals") and score_pts >= _rule("score_entry_threshold"):
                        # Calculate add quantity
                        size = size_position(snap, vix)
                        add_shares = max(1, size // int(price + 1))
                        limit_price = wall_below["strike"] if wall_below and wall_below["dist_pct"] > -5 else price
                        signals_fired = []
                        if rsi_ok: signals_fired.append(f"RSI {rsi:.0f} oversold")
                        if bullish_opts: signals_fired.append(f"Flow {opt_signal}")
                        if mp_pulling_up: signals_fired.append(f"MP${mp:.0f} pulling up")
                        if has_insider: signals_fired.append(f"Insider {ins_signal}")
                        if news_bullish: signals_fired.append(f"News {news_sig}/{news_str_val}")

                        news_note = f" 📰 {news_trigger[:60]}." if news_bullish else ""
                        macro_note = f" 📡 Macro {macro_pulse}: {', '.join(macro_active[:2]).replace('_',' ')}." if macro_active else ""
                        add("ACTION", t, acct_name,
                            f"ADD {add_shares}sh @ ${limit_price:.2f}",
                            f"{pct:.1f}% | Score {score_pts}/180 | {' + '.join(signals_fired)}. "
                            f"Add {add_shares}sh @ ${limit_price:.2f} limit (${add_shares*limit_price:.0f}). "
                            f"Floor: ${floor:.0f} | Target: ${target:.0f}.{news_note}{macro_note}",
                            "green", signals_str)

                    elif earn_ok and score_pts >= _rule("score_entry_threshold"):
                        add("WATCH", t, acct_name, "ADD ZONE - CONFIRM SIGNALS",
                            f"{pct:.1f}% | Score {score_pts}/180. "
                            f"Options: {opt_signal} | RSI: {rsi:.0f if rsi else '-'}. "
                            f"Need 2+ bullish signals to add. Floor: ${floor:.0f}.",
                            "blue", signals_str)

                    elif earn_ok:
                        add("WATCH", t, acct_name, "ADD ZONE - SCORE TOO LOW",
                            f"{pct:.1f}% | Score {score_pts}/180 (need ≥{_rule('score_entry_threshold')}). HOLD - don't add yet.",
                            "blue", signals_str)

                elif pct < -15:
                    # Disaster zone - but check insider signal before flagging exit
                    if has_insider:
                        add("WATCH", t, acct_name, "DOWN >15% - INSIDER HOLDING",
                            f"{pct:.1f}% | [{ins_signal}] {ins_desc}. "
                            f"Insider conviction = do NOT exit on price alone. Verify thesis.",
                            "blue", signals_str)
                    else:
                        add("URGENT", t, acct_name, "DISASTER STOP ZONE - VERIFY THESIS",
                            f"{pct:.1f}% | Exit ONLY if thesis broken. NOT price-only exit. "
                            f"Floor: ${floor:.0f}. Check: revenue growth, moat, narrative intact?",
                            "red", signals_str)

            # ── TYPE I - Income (EPD etc) ─────────────────────────────────────
            elif ptype == "I":
                if pct < -20:
                    add("WATCH", t, acct_name, "INCOME: CHECK DISTRIBUTION INTACT",
                        f"{pct:.1f}% - verify distribution not cut. Not an exit on price alone.",
                        "orange", signals_str)
                # Max pain drift up on income = bonus - note it
                if mp and mp_dist and mp_dist > 3 and mp_days and mp_days <= 3:
                    add("WATCH", t, acct_name, f"MAX PAIN LIFT → ${mp:.0f}",
                        f"Income position getting mechanical lift from max pain. "
                        f"Hold - this is free upside on top of distribution yield.",
                        "blue", signals_str)

            # ── TYPE Spec ─────────────────────────────────────────────────────
            elif ptype == "Spec":
                # Run spec_score to get structured conviction signal
                _spec_result = None
                if is_spec_candidate(snap):
                    try:
                        _spec_result = score_spec(
                            snap,
                            insider_buy=has_insider,
                            insider_signal=ins_signal,
                            pattern_result=chart_pat,
                            next_catalyst=pos.get("next_catalyst"),
                        )
                    except Exception:
                        pass

                _spec_score_str = ""
                if _spec_result and not _spec_result.disqualified:
                    _spec_score_str = f" | SPEC {_spec_result.total}/150 [{_spec_result.signal.upper()}]"

                if price < 1.0:
                    add("URGENT", t, acct_name, "SPEC: DELISTING RISK",
                        f"${price:.2f} below $1.00 - NYSE/NASDAQ delisting threshold. "
                        f"Exit unless you have confirmed catalyst within 30 days.",
                        "red", signals_str)
                elif t == "BBAI" and price < 2.50:
                    add("URGENT", t, acct_name, "EXIT SPEC - BELOW FLOOR",
                        f"${price:.2f} < $2.50 floor. Exit immediately. Never average down on spec.",
                        "red", signals_str)
                elif _spec_result and not _spec_result.disqualified and _spec_result.total >= 90:
                    # Strong spec score - surface as ADD candidate if not in big loss
                    if pct >= -15 and not news_blocks_add:
                        add("BUY", t, acct_name, f"SPEC ADD - STRONG{_spec_score_str}",
                            f"${price:.2f} | Runway: {_spec_result.runway_note} | "
                            f"{_spec_result.catalyst_note or 'No near catalyst'}. "
                            f"Max spec position: $500.",
                            "green", signals_str)
                    else:
                        add("WATCH", t, acct_name, f"SPEC STRONG BUT {'NEWS RISK' if news_blocks_add else 'IN LOSS'}{_spec_score_str}",
                            f"${price:.2f} ({pct:.1f}%) | {_spec_result.catalyst_note or ''} "
                            f"{'THESIS NEGATIVE NEWS - no add.' if news_blocks_add else 'In loss zone - no add per rules.'}",
                            "yellow", signals_str)
                elif pct <= -30:
                    add("WATCH", t, acct_name, "SPEC: VERIFY THESIS",
                        f"{pct:.1f}%{_spec_score_str} | Contract cancellations? DOD spending cuts? "
                        f"If thesis broken → exit all. Never add to losing spec.",
                        "orange", signals_str)

            # ── TYPE Lifetime (TOD) ───────────────────────────────────────────
            elif ptype == "Lifetime":
                # Lifetime = never stop, never exit on price
                # BUT: flag earnings, flag unusual options, flag max pain if huge
                if opt_signal == "UNUSUAL_CALLS":
                    add("WATCH", t, acct_name, "UNUSUAL CALLS - LIFETIME HOLD",
                        f"Flow: {opt_signal} | {flow.get('note','')} "
                        f"Whale accumulation detected. Confirms lifetime thesis. HOLD all shares.",
                        "blue", signals_str)
                if mp and mp_dist and mp_dist < -8 and mp_days and mp_days <= 2:
                    add("WATCH", t, acct_name, f"MAX PAIN ${mp:.0f} BELOW - DRIFT DOWN TODAY",
                        f"Price ${price:.2f} is {abs(mp_dist):.1f}% ABOVE max pain ${mp:.0f}. "
                        f"Expiry {mp_days}d. Don't panic - lifetime hold. "
                        f"Potential short-term dip today, recover Monday.",
                        "blue", signals_str)

            # ── BEARISH PATTERN override (all non-Lifetime) ───────────────────
            if ptype not in ("Lifetime",) and cp_sig == "bearish" and cp_conf >= 0.65:
                pname = chart_pat.get("pattern", "").replace("_", " ").title()
                # If insider signal is strong, downgrade urgency
                if has_insider:
                    add("WATCH", t, acct_name, f"BEARISH PATTERN ({pname}) - BUT INSIDER BUYING",
                        f"{cp_conf:.0%} confidence pattern. However [{ins_signal}] insider buying. "
                        f"Conflicting signals - tighten stop, don't add, don't exit.",
                        "orange", signals_str)
                else:
                    add("WATCH", t, acct_name, f"BEARISH PATTERN: {pname.upper()}",
                        f"{cp_conf:.0%} confidence. Tighten stop or reduce before confirmation. "
                        f"Floor: ${wall_below['strike']:.0f}." if wall_below else
                        f"{cp_conf:.0%} confidence. Tighten stop.",
                        "orange", signals_str)

            # ── BULLISH RSI DIVERGENCE on L ───────────────────────────────────
            if ptype == "L" and rsi and rsi_div.get("divergence") == "bullish" and -15 <= pct <= 0:
                add("WATCH", t, acct_name, "BULLISH RSI DIVERGENCE",
                    f"RSI {rsi:.0f} diverging bullish while price {pct:.1f}%. Potential reversal. "
                    f"Floor: ${wall_below['strike']:.0f}." if wall_below else
                    f"RSI {rsi:.0f} diverging bullish.",
                    "blue", signals_str)

        # ── Pending orders (same as v2) ───────────────────────────────────────
        for pos in acct.get("positions", []):
            t     = pos["ticker"]
            price = (snapshots.get(t) or {}).get("price") or pos["avg_cost"]
            flow  = opt.get(t, {})
            mp    = flow.get("max_pain")
            mp_dist = flow.get("max_pain_dist_pct")
            for order in pos.get("pending_orders", []):
                if order.get("status") != "open":
                    continue
                op       = order.get("order", "")
                op_price = order.get("price", 0)
                op_sh    = order.get("shares", 0)
                note     = order.get("note", "")
                if not op_price:
                    continue
                gap_pct = abs(price - op_price) / price * 100
                suffix  = f" - {note}" if note else ""
                # Add max pain context: if limit is FAR from max pain, will it fill?
                mp_context = ""
                if mp and mp_dist is not None:
                    if op == "buy" and op_price < price and mp_dist < -4:
                        mp_context = f" Max pain ${mp:.0f} pulling DOWN - limit may fill this week."
                    elif op == "buy" and op_price < price and mp_dist > 4:
                        mp_context = f" Max pain ${mp:.0f} pulling UP - limit unlikely to fill this week."
                if gap_pct <= 1:
                    add("URGENT", t, acct_name, "ORDER FILLING NOW - CHECK FIDELITY",
                        f"{'BUY' if op=='buy' else 'SELL'} {op_sh}sh @${op_price:.2f} | "
                        f"Current ${price:.2f} | {gap_pct:.1f}% gap.{suffix}{mp_context}",
                        "green" if op == "buy" else "orange")
                elif gap_pct <= 3:
                    add("ACTION", t, acct_name, "ORDER VERY NEAR",
                        f"{'BUY' if op=='buy' else 'SELL'} {op_sh}sh @${op_price:.2f} | "
                        f"Current ${price:.2f} | {gap_pct:.1f}% gap.{suffix}{mp_context}",
                        "blue")
                elif gap_pct <= 8:
                    add("WATCH", t, acct_name, "PENDING ORDER",
                        f"{'BUY' if op=='buy' else 'SELL'} {op_sh}sh @${op_price:.2f} | "
                        f"Current ${price:.2f} | {gap_pct:.1f}% away.{suffix}{mp_context}",
                        "blue")

        # Watchlist orders
        for wl in acct.get("watchlist_orders", []):
            t        = wl["ticker"]
            price    = (snapshots.get(t) or {}).get("price")
            op_price = wl.get("price", 0)
            if price and op_price:
                gap_pct = abs(price - op_price) / price * 100
                if gap_pct <= 5:
                    stop_str = f" | Stop if fills: ${wl.get('stop_if_fills',0):.2f}" if wl.get("stop_if_fills") else ""
                    add("WATCH", t, acct_name, "WATCHLIST ORDER NEAR",
                        f"BUY @${op_price:.2f} | Current ${price:.2f} | {gap_pct:.1f}% gap{stop_str} | {wl.get('thesis','')}",
                        "blue")

    # Sort: URGENT → ACTION → WATCH → INFO
    items.sort(key=lambda x: _PRIO_ORDER.get(x.get("priority", "INFO"), 3))
    for i, item in enumerate(items, 1):
        item["num"] = i
    return items


def render_action_items_html(items: list[dict]) -> str:
    if not items:
        return '<div style="color:#64748b;font-size:12px;padding:8px;">No urgent actions today - monitor positions.</div>'

    prio_cfg = {
        "URGENT": ("#ef4444", "🚨", "#fff5f5"),
        "ACTION": ("#059669", "✅", "#f0fdf4"),
        "WATCH":  ("#d97706", "⚡", "#fffbeb"),
        "INFO":   ("#3b82f6", "ℹ️",  "#eff6ff"),
    }

    rows = ""
    for item in items:
        p    = item.get("priority", "INFO")
        cfg  = prio_cfg.get(p, ("#64748b", "•", "#f8fafc"))
        col, icon, bg = cfg
        num  = item.get("num", "")
        tick = item.get("ticker", "")
        acct = item.get("account", "")
        verb = item.get("verb", "")
        det  = item.get("detail", "")
        rows += (
            f'<tr style="background:{bg};">'
            f'<td style="color:#94a3b8;font-weight:600;font-size:11px;width:28px;">{num}</td>'
            f'<td style="width:22px;font-size:13px;">{icon}</td>'
            f'<td style="color:{col};font-weight:700;font-size:10px;width:60px;">{p}</td>'
            f'<td style="font-weight:700;font-size:12px;width:45px;">{tick}</td>'
            f'<td style="color:#64748b;font-size:10px;width:55px;">{acct}</td>'
            f'<td style="color:{col};font-weight:700;font-size:11px;width:220px;">{verb}</td>'
            f'<td style="color:#374151;font-size:11px;line-height:1.5;">{det}</td>'
            f'</tr>'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;">'
        '<tr style="background:#f8fafc;">'
        '<th style="text-align:left;font-size:10px;color:#94a3b8;padding:4px 6px;" colspan="2">#</th>'
        '<th style="text-align:left;font-size:10px;color:#94a3b8;padding:4px;">Priority</th>'
        '<th style="text-align:left;font-size:10px;color:#94a3b8;padding:4px;">Ticker</th>'
        '<th style="text-align:left;font-size:10px;color:#94a3b8;padding:4px;">Acct</th>'
        '<th style="text-align:left;font-size:10px;color:#94a3b8;padding:4px;">Action</th>'
        '<th style="text-align:left;font-size:10px;color:#94a3b8;padding:4px;">Detail</th>'
        '</tr>'
        + rows
        + '</table>'
    )
