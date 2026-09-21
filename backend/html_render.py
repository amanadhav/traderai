"""
html_render.py - HTML dashboard generation (tracker.html + daily_read).

Contains:
  POSITION_MACRO         - per-ticker macro narrative blurbs
  generate_daily_read    - rule-based "Today's Read" lines
  render_daily_read_html - Today's Read as HTML
  generate_html          - full tracker.html string (orchestrator)
  _build_html            - final HTML template assembly

Pulls live action items from action_engine.generate_action_items_v3.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from positions import calc_pnl
from action_engine import generate_action_items_v3, render_action_items_html


POSITION_MACRO = {
    "EPD": "Iran War / Hormuz - US LNG export beneficiary",
    "GLD": "Iran War + De-dollarization hedge",
    "RTX": "Iran War + Europe Rearmament - defense premium",
    "NOC": "Iran War + Europe Rearmament - defense premium",
    "MP":  "Rare Earth Decoupling - China export ban catalyst",
    "CRM": "Agentic AI Infrastructure - Agentforce thesis",
    "NVDA": "AI Infrastructure - GPU monopoly",
    "AMD":  "AI Infrastructure - data center alternative",
    "ASML": "AI Infrastructure - EUV lithography monopoly",
    "TSM":  "AI Infrastructure + Taiwan tail risk",
    "MDT":  "Healthcare mean reversion - CE mark, analyst target $109",
    "NKE":  "Consumer oversold bounce - multi-year low, new CEO",
    "BJ":   "Consumer recession hedge - warehouse clubs outperform in downturns",
    "BBAI": "AI defense spec - hold unless drops below $2.50",
    "NVO":  "GLP-1 / Ozempic pipeline dominance",
    "NFLX": "Streaming - sticky in recession, ad tier growing",
}

def generate_daily_read(data: dict, snapshots: dict, div_info: dict,
                        ticker_news: dict, market_snaps: dict) -> list[tuple[str, str]]:
    """Return list of (color, text) tuples for Today's Read section."""
    lines: list[tuple[str, str]] = []

    # ── Market conditions ──────────────────────────────────────────────────
    vix = (market_snaps.get("^VIX") or {}).get("price")
    spy_rsi = (market_snaps.get("SPY") or {}).get("rsi")
    qqq_rsi = (market_snaps.get("QQQ") or {}).get("rsi")

    if vix:
        if vix > 35:
            lines.append(("red", f"🚨 VIX {vix:.1f} - EXTREME FEAR. Reduce all sizing 50%. No new lump sum entries today."))
        elif vix > 25:
            lines.append(("yellow", f"⚡ VIX {vix:.1f} - Elevated. Reduce sizing 25% on all new entries."))
        else:
            lines.append(("green", f"✅ VIX {vix:.1f} - Normal. Standard sizing applies."))

    if spy_rsi:
        if spy_rsi > 75:
            lines.append(("red", f"🚨 SPY RSI {spy_rsi:.1f} - OVERBOUGHT. No new lump sum entries. Wait for pullback."))
        elif spy_rsi < 35:
            lines.append(("green", f"🚀 SPY RSI {spy_rsi:.1f} - OVERSOLD. Buy aggressively - best entry environment."))
        else:
            lines.append(("neutral", f"📊 SPY RSI {spy_rsi:.1f} - Neutral market conditions."))

    if qqq_rsi and qqq_rsi > 75:
        lines.append(("yellow", f"⚠️ QQQ RSI {qqq_rsi:.1f} - Tech overbought. Be selective on new tech entries."))

    lines.append(("divider", ""))

    # ── Position health checks ─────────────────────────────────────────────
    for acct_name, acct in data["accounts"].items():
        for pos in acct.get("positions", []):
            t = pos["ticker"]
            s = snapshots.get(t, {})
            price = s.get("price") or pos["avg_cost"]
            avg = pos["avg_cost"]
            pct = ((price - avg) / avg) * 100
            ptype = pos.get("type", "")
            stop = pos.get("stop")

            # Stop proximity
            if stop and price > stop:
                gap_pct = ((price - stop) / price) * 100
                if gap_pct < 8:
                    lines.append(("red", f"🔴 {t} (${price:.2f}) - Stop ${stop:.2f} · only {gap_pct:.1f}% buffer. Monitor closely."))

            # Swing rules
            if ptype == "S":
                if pct >= 20:
                    lines.append(("green", f"✅ {t} SWING +{pct:.1f}% - TARGET HIT. Sell all. Rules say exit at +20%."))
                elif pct >= 10:
                    lines.append(("green", f"✅ {t} SWING +{pct:.1f}% - Sell 50%. Move stop to breakeven now."))
                elif pct >= 5:
                    lines.append(("green", f"💡 {t} SWING +{pct:.1f}% - Move stop to breakeven. Protect the gain."))
                elif pct <= -8:
                    lines.append(("red", f"🚨 {t} SWING {pct:.1f}% - STOP LEVEL BREACHED. Verify GTC executed in Fidelity."))

            # Long rules
            elif ptype == "L":
                if pct >= 30:
                    lines.append(("green", f"✅ {t} LONG +{pct:.1f}% - Sell 50% per profit ladder. Reassess thesis."))
                elif pct >= 15:
                    lines.append(("green", f"✅ {t} LONG +{pct:.1f}% - Sell 25% per profit ladder."))
                elif pct <= -15:
                    lines.append(("red", f"🚨 {t} LONG {pct:.1f}% - DISASTER STOP ZONE. Exit only on thesis break - not just price."))
                elif pct <= -8:
                    lines.append(("yellow", f"⚡ {t} LONG {pct:.1f}% - ADD ZONE. Type L rule: this is NOT an exit. Add if thesis intact + earnings >15 days away."))

            # Spec rules
            elif ptype == "Spec":
                floor_check = pos.get("notes", "")
                if price < 2.50 and t == "BBAI":
                    lines.append(("red", f"🚨 {t} SPEC ${price:.2f} - BELOW $2.50 FLOOR. Re-evaluate thesis NOW."))
                elif pct <= -30:
                    lines.append(("yellow", f"⚠️ {t} SPEC {pct:.1f}% - Check thesis. Exit if contract cancellations or floor breached."))

    lines.append(("divider", ""))

    # ── Big movers + macro dot-connection ─────────────────────────────────
    movers_found = False
    for t, snap in snapshots.items():
        day_pct = snap.get("pct_chg_today") or 0
        if abs(day_pct) < 2:
            continue
        movers_found = True
        narrative = POSITION_MACRO.get(t, "")
        news = ticker_news.get(t, [])
        headline = news[0]["title"] if news else "No headline found - check news manually"
        arrow = "⬆️" if day_pct >= 0 else "⬇️"
        narrative_str = f"  [{narrative}]" if narrative else ""
        color = "green" if day_pct >= 0 else "red"
        lines.append((color, f"{arrow} {t} {'+' if day_pct >= 0 else ''}{day_pct:.1f}%{narrative_str}"))
        lines.append(("sub", f"   → {headline[:110]}"))

    if not movers_found:
        lines.append(("neutral", "📊 No positions moved >2% today. Quiet session."))

    lines.append(("divider", ""))

    # ── Upcoming dividends ─────────────────────────────────────────────────
    div_found = False
    for t, d in div_info.items():
        if d.get("ex_date"):
            shares = 0
            for acct in data["accounts"].values():
                for p in acct.get("positions", []):
                    if p["ticker"] == t:
                        shares = p["shares"]
            income = (d.get("annual_div") or 0) * shares
            div_found = True
            lines.append(("blue", f"💰 {t} ex-div {d['ex_date']} · Pay {d.get('div_date','?')} · ${d.get('annual_div',0):.2f}/sh · ${income:.2f}/yr projected"))
    if not div_found:
        lines.append(("neutral", "No upcoming ex-dividend dates detected."))

    return lines


def render_daily_read_html(lines: list[tuple[str, str]]) -> str:
    color_map = {
        "red":     "#ef4444",
        "green":   "#10b981",
        "yellow":  "#d97706",
        "blue":    "#3b82f6",
        "neutral": "#64748b",
        "sub":     "#94a3b8",
    }
    html = ""
    for color, text in lines:
        if color == "divider":
            html += '<hr style="border:none;border-top:1px solid #f1f5f9;margin:8px 0;">'
            continue
        c = color_map.get(color, "#374151")
        weight = "600" if color not in ("sub", "neutral") else "400"
        html += f'<div style="font-size:11px;color:{c};font-weight:{weight};padding:3px 0;line-height:1.5;">{text}</div>\n'
    return html


# ── Action engine (moved to action_engine.py - re-exported for back-compat) ──

from action_engine import (
    generate_action_items_v2,
    generate_action_items_v3,
    render_action_items_html,
    _PRIO_ORDER,
)


# ── HTML dashboard generator ───────────────────────────────────────────────

def generate_html(data: dict, snapshots: dict, market_open: bool, market_status_str: str,
                  alerts: list[str], action_items: list[str], macro_status: dict,
                  div_info: dict, today: str,
                  ticker_news: dict | None = None,
                  pattern_results: dict | None = None,
                  etf_snapshots: dict | None = None,
                  market_snaps: dict | None = None,
                  insider_signals: dict | None = None,
                  options_flows: dict | None = None,
                  macro_results: dict | None = None) -> str:

    roth = data["accounts"]["ROTH"]
    tod = data["accounts"]["TOD"]
    ticker_news = ticker_news or {}
    etf_snapshots = etf_snapshots or {}
    market_snaps = market_snaps or {}
    macro_results = macro_results or {}

    # ── Generate action items v3 (5-signal synthesis) ─────────────────────
    action_items_v3 = generate_action_items_v3(
        data, snapshots, pattern_results, market_snaps, div_info,
        insider_signals=insider_signals, options_flows=options_flows,
        ticker_news=ticker_news, macro_results=macro_results,
    )
    action_items_html = render_action_items_html(action_items_v3)

    # ── Generate rule-based daily read ────────────────────────────────────
    daily_read_lines = generate_daily_read(data, snapshots, div_info, ticker_news, market_snaps)
    daily_read_html = render_daily_read_html(daily_read_lines)

    def calc_total(acct, snaps):
        total = acct.get("cash", 0)
        for p in acct.get("positions", []):
            s = snaps.get(p["ticker"], {})
            price = s.get("price") or p["avg_cost"]
            total += price * p["shares"]
        return total

    roth_total = calc_total(roth, snapshots)
    tod_total = calc_total(tod, snapshots)
    grand_total = roth_total + tod_total

    def type_badge(t):
        m = {"S": ("t-swing", "SWING"), "L": ("t-long", "LONG"), "I": ("t-income", "INCOME"),
             "Lifetime": ("t-life", "LIFE"), "Spec": ("t-spec", "SPEC")}
        cls, lbl = m.get(t, ("badge", t))
        return f'<span class="{cls}">{lbl}</span>'

    def gl_cls(v):
        return "gl-pos" if v > 0 else ("gl-neg" if v < 0 else "")

    def sign(v):
        return "+" if v >= 0 else ""

    # ── Build ROTH positions rows ──────────────────────────────────────────
    roth_rows = ""
    roth_pos_total = roth_pos_gl = 0
    for p in roth.get("positions", []):
        t = p["ticker"]
        s = snapshots.get(t, {})
        price = s.get("price") or p["avg_cost"]
        shares = p["shares"]
        cost_basis = p["avg_cost"] * shares
        value = price * shares
        gl_d = value - cost_basis
        gl_p = (gl_d / cost_basis * 100) if cost_basis else 0
        roth_pos_total += value
        roth_pos_gl += gl_d
        stop = p.get("stop")
        stop_str = f"${stop:.2f}" if stop else "-"
        name = COMPANY_NAMES.get(t, "")
        rsi = s.get("rsi")
        rsi_str = f"{rsi:.1f}" if rsi else "-"
        rsi_cls = ""
        if rsi:
            rsi_cls = "rsi-ok" if rsi < 35 else ("rsi-hot" if rsi > 70 else "rsi-watch")
        day_pct = s.get("pct_chg_today") or 0
        day_cls = "gl-pos" if day_pct >= 0 else "gl-neg"
        roth_rows += (
            f"<tr><td><div class=\"sym\">{t}</div><div class=\"sym-name\">{name}</div></td>"
            f"<td>{type_badge(p['type'])}</td>"
            f"<td>${p['avg_cost']:.2f}</td>"
            f"<td><strong>${price:.2f}</strong></td>"
            f"<td>{shares}</td>"
            f"<td>${value:,.0f}</td>"
            f"<td class=\"{gl_cls(gl_d)}\">{sign(gl_d)}${abs(gl_d):.0f}</td>"
            f"<td class=\"{gl_cls(gl_p)}\">{sign(gl_p)}{gl_p:.1f}%</td>"
            f"<td>{stop_str}</td>"
            f"<td class=\"{rsi_cls}\">{rsi_str}</td></tr>\n"
        )
    roth_cash = roth.get("cash", 0)
    gl_color = "#4ade80" if roth_pos_gl >= 0 else "#f87171"
    roth_rows += (
        f"<tr style=\"background:#1e293b;\">"
        f"<td colspan=\"5\" style=\"font-weight:700;font-size:11px;padding:8px 10px;color:white;\">ROTH POSITIONS TOTAL</td>"
        f"<td style=\"padding:8px 10px;font-weight:700;color:white;\">${roth_pos_total:,.0f}</td>"
        f"<td style=\"padding:8px 10px;font-weight:700;color:{gl_color};\">{sign(roth_pos_gl)}${abs(roth_pos_gl):.0f}</td>"
        f"<td colspan=\"3\" style=\"padding:8px 10px;font-size:10px;color:#94a3b8;\">+${roth_cash:,.0f} cash</td></tr>"
    )

    # ── Build TOD positions rows ───────────────────────────────────────────
    tod_rows = ""
    tod_pos_total = tod_pos_gl = 0
    for p in tod.get("positions", []):
        t = p["ticker"]
        s = snapshots.get(t, {})
        price = s.get("price") or p["avg_cost"]
        shares = p["shares"]
        cost_basis = p["avg_cost"] * shares
        value = price * shares
        gl_d = value - cost_basis
        gl_p = (gl_d / cost_basis * 100) if cost_basis else 0
        tod_pos_total += value
        tod_pos_gl += gl_d
        name = COMPANY_NAMES.get(t, "")
        thesis = p.get("thesis", "")[:65]
        tod_rows += (
            f"<tr><td><div class=\"sym\">{t}</div><div class=\"sym-name\">{name}</div></td>"
            f"<td>{type_badge(p['type'])}</td>"
            f"<td>${p['avg_cost']:.2f}</td>"
            f"<td><strong>${price:.2f}</strong></td>"
            f"<td>{shares}</td>"
            f"<td>${value:,.0f}</td>"
            f"<td class=\"{gl_cls(gl_d)}\">{sign(gl_d)}${abs(gl_d):.0f}</td>"
            f"<td class=\"{gl_cls(gl_p)}\">{sign(gl_p)}{gl_p:.1f}%</td>"
            f"<td style=\"font-size:10px;color:#64748b;\">{thesis}</td></tr>\n"
        )
    tod_cash = tod.get("cash", 0)
    gl_color_tod = "#4ade80" if tod_pos_gl >= 0 else "#f87171"
    tod_cost = tod_pos_total - tod_pos_gl
    tod_gl_pct = (tod_pos_gl / tod_cost * 100) if tod_cost else 0
    tod_rows += (
        f"<tr style=\"background:#1e293b;\">"
        f"<td colspan=\"5\" style=\"font-weight:700;font-size:11px;padding:8px 10px;color:white;\">TOD POSITIONS TOTAL</td>"
        f"<td style=\"padding:8px 10px;font-weight:700;color:white;\">${tod_pos_total:,.0f}</td>"
        f"<td style=\"padding:8px 10px;font-weight:700;color:{gl_color_tod};\">{sign(tod_pos_gl)}${abs(tod_pos_gl):.0f}</td>"
        f"<td style=\"padding:8px 10px;font-weight:700;color:{gl_color_tod};\">{sign(tod_gl_pct)}{tod_gl_pct:.1f}%</td>"
        f"<td style=\"padding:8px 10px;font-size:10px;color:#94a3b8;\">+${tod_cash:,.0f} cash</td></tr>"
    )

    # ── ROTH pending orders grid ───────────────────────────────────────────
    roth_pending = ""
    for pos in roth.get("positions", []):
        for o in pos.get("pending_orders", []):
            t = pos["ticker"]
            s = snapshots.get(t, {})
            current = s.get("price") or 0
            price = o.get("price") or 0
            gap = abs(current - price) if current and price else 0
            card_cls = "warn" if 0 < gap < 1.0 else ""
            note = o.get("note", "GTC open")
            roth_pending += (
                f"<div class=\"order-card {card_cls}\">"
                f"<div class=\"order-sym\">{t}</div>"
                f"<div class=\"order-detail\">{COMPANY_NAMES.get(t,'')} · {pos.get('type','')} · ${current:.2f} now</div>"
                f"<div class=\"order-price\">${price:.2f} · {o.get('shares',0)}sh</div>"
                f"<div class=\"order-status\" style=\"color:#3b82f6;\">{note}</div></div>\n"
            )
    for o in roth.get("watchlist_orders", []):
        t = o.get("ticker", "")
        s = snapshots.get(t, {})
        current = s.get("price") or 0
        roth_pending += (
            f"<div class=\"order-card\">"
            f"<div class=\"order-sym\">{t} 👀 Watchlist</div>"
            f"<div class=\"order-detail\">{o.get('thesis','')}</div>"
            f"<div class=\"order-price\">${o.get('price',0):.2f} buy · stop ${o.get('stop_if_fills',0):.2f} if fills</div>"
            f"<div class=\"order-status\" style=\"color:#d97706;\">Current: ${current:.2f}</div></div>\n"
        )
    if not roth_pending:
        roth_pending = "<p style=\"color:#94a3b8;font-size:12px;\">No pending ROTH orders.</p>"

    # ── TOD pending orders grid ────────────────────────────────────────────
    tod_pending = ""
    for pos in tod.get("positions", []):
        for o in pos.get("pending_orders", []):
            t = pos["ticker"]
            s = snapshots.get(t, {})
            current = s.get("price") or 0
            price = o.get("price") or 0
            note = o.get("note", "GTC open")
            tod_pending += (
                f"<div class=\"order-card tod\">"
                f"<div class=\"order-sym\">{t}</div>"
                f"<div class=\"order-detail\">{COMPANY_NAMES.get(t,'')} · {pos.get('type','')}</div>"
                f"<div class=\"order-price\">${price:.2f} · {o.get('shares',0)}sh</div>"
                f"<div class=\"order-status\" style=\"color:#10b981;\">{note} · Current: ${current:.2f}</div></div>\n"
            )
    if not tod_pending:
        tod_pending = "<p style=\"color:#94a3b8;font-size:12px;\">No pending TOD orders.</p>"

    # ── Today tab action cards ─────────────────────────────────────────────
    today_cards = ""
    for t, snap in snapshots.items():
        pct = snap.get("pct_chg_today") or 0
        if abs(pct) >= 2:
            news = ticker_news.get(t, [])
            headline = news[0]["title"] if news else "No headline found"
            arrow = "⬆️" if pct >= 0 else "⬇️"
            color = "#10b981" if pct >= 0 else "#ef4444"
            status_txt = "✅ Thesis intact - check news" if pct >= 0 else "⚠️ Review thesis - check news"
            today_cards += (
                f"<div class=\"order-card\" style=\"border-left-color:{color};\">"
                f"<div class=\"order-sym\">{arrow} {t} {sign(pct)}{pct:.1f}%</div>"
                f"<div class=\"order-detail\">Big mover today</div>"
                f"<div class=\"order-price\" style=\"font-size:12px;\">{headline[:100]}</div>"
                f"<div class=\"order-status\" style=\"color:{color};\">{status_txt}</div></div>\n"
            )
    for t, snap in snapshots.items():
        dte = snap.get("days_to_earnings")
        if dte is not None and 0 <= dte <= 3:
            today_cards += (
                f"<div class=\"order-card\" style=\"border-left-color:#ef4444;background:#fff1f2;\">"
                f"<div class=\"order-sym\">🚨 {t} EARNINGS IN {dte} DAYS</div>"
                f"<div class=\"order-detail\">AUTO-DISQUALIFIER for new entries</div>"
                f"<div class=\"order-price\">Review position type - no adds while within window</div>"
                f"<div class=\"order-status\" style=\"color:#ef4444;\">URGENT - review before market open</div></div>\n"
            )
    for a in alerts:
        if "CLOSE TO FILL" in a:
            today_cards += (
                f"<div class=\"order-card warn\">"
                f"<div class=\"order-sym\">⚡ GTC NEAR FILL</div>"
                f"<div class=\"order-detail\">{a}</div>"
                f"<div class=\"order-price\">Check Fidelity - may need action</div>"
                f"<div class=\"order-status\" style=\"color:#d97706;\">When fills: update stop per pending orders tab</div></div>\n"
            )
    if not today_cards:
        today_cards = (
            "<div class=\"order-card\" style=\"border-left-color:#10b981;background:#f0fdf4;\">"
            "<div class=\"order-sym\">✅ No urgent actions today</div>"
            "<div class=\"order-detail\">All positions tracking normally</div>"
            "<div class=\"order-price\">Monitor pending GTC orders</div>"
            "<div class=\"order-status\" style=\"color:#10b981;\">Check conditionals table below</div></div>"
        )

    # ── Conditional actions table ──────────────────────────────────────────
    cond_rows = ""
    for acct_name, acct in data["accounts"].items():
        acct_id = acct.get("id", "")
        for pos in acct.get("positions", []):
            for o in pos.get("pending_orders", []):
                t = pos["ticker"]
                note = o.get("note", "Monitor after fill")
                action_desc = o.get("order", "").upper()
                cond_rows += (
                    f"<tr><td>{t} {action_desc} {o.get('shares',0)}sh @${o.get('price',0):.2f} fills</td>"
                    f"<td>{note}</td><td>{acct_name} {acct_id}</td></tr>\n"
                )
        for o in acct.get("watchlist_orders", []):
            cond_rows += (
                f"<tr><td>{o.get('ticker','')} BUY @${o.get('price',0):.2f} triggers</td>"
                f"<td>Set stop @${o.get('stop_if_fills',0):.2f} GTC immediately</td>"
                f"<td>{acct_name}</td></tr>\n"
            )
    if not cond_rows:
        cond_rows = "<tr><td colspan=\"3\" style=\"color:#94a3b8;\">No pending conditional actions</td></tr>"

    # ── Dividend calendar ──────────────────────────────────────────────────
    div_event_rows = ""
    for t, d in div_info.items():
        if not (d.get("ex_date") or d.get("div_date")):
            continue
        shares = 0
        for acct in data["accounts"].values():
            for p in acct.get("positions", []):
                if p["ticker"] == t:
                    shares = p["shares"]
        annual_div = d.get("annual_div") or 0
        income = annual_div * shares
        div_event_rows += (
            f"<tr><td><strong>{t}</strong></td>"
            f"<td>{d.get('ex_date','-')}</td>"
            f"<td>{d.get('div_date','-')}</td>"
            f"<td>{d.get('div_yield','-')}%</td>"
            f"<td>${annual_div:.2f}/sh</td>"
            f"<td style=\"color:#10b981;font-weight:600;\">${income:.2f}/yr</td></tr>\n"
        )
    if not div_event_rows:
        div_event_rows = "<tr><td colspan=\"6\" style=\"color:#94a3b8;\">No upcoming dividends detected</td></tr>"

    # ── Earnings calendar ──────────────────────────────────────────────────
    earn_event_rows = ""
    earn_items = [(t, s.get("days_to_earnings")) for t, s in snapshots.items()
                  if s.get("days_to_earnings") is not None and 0 <= s["days_to_earnings"] <= 45]
    earn_items.sort(key=lambda x: x[1])
    for t, dte in earn_items:
        if dte <= 3:
            flag = "🚨 URGENT - disqualifier"
            row_style = " style=\"background:#fff1f2;\""
        elif dte <= 15:
            flag = "⚠️ DISQUALIFIER"
            row_style = " style=\"background:#fffbeb;\""
        else:
            flag = "📅 Watch"
            row_style = ""
        earn_event_rows += (
            f"<tr{row_style}><td><strong>{t}</strong></td>"
            f"<td>{dte} days</td><td>{flag}</td></tr>\n"
        )
    if not earn_event_rows:
        earn_event_rows = "<tr><td colspan=\"3\" style=\"color:#94a3b8;\">No earnings in next 45 days</td></tr>"

    # ── ETF watchlist rows ─────────────────────────────────────────────────
    ETF_META = {
        "ITA": ("US Defense", "$210-216 · 5sh · TOD · wait MACD"),
        "DFEN": ("Defense 3x Lev", "Too leveraged - skip"),
        "GLD": ("Gold", "ROTH add if dips below $415"),
        "XLE": ("Energy", "Iran war premium - $1K ROTH or TOD"),
        "REMX": ("Rare Earth", "MP covers thesis now"),
        "ARKQ": ("Drones / Auto", "Wait RSI < 45"),
        "BOTZ": ("Robotics / AI", "Wait RSI < 45"),
        "NUCL": ("Nuclear Energy", "Wait RSI < 50"),
        "LIT": ("Lithium / Battery", "Wait RSI < 45"),
        "SMH": ("Semis (VanEck)", "Wait RSI < 50 for re-entry"),
        "SOXX": ("Semis (iShares)", "Wait RSI < 50"),
        "ARKG": ("Genomics / Bio", "Future biotech exposure"),
    }
    etf_rows = ""
    all_etf_snaps = {**snapshots, **etf_snapshots}
    for etf, (theme, entry_note) in ETF_META.items():
        s = all_etf_snaps.get(etf, {})
        rsi = s.get("rsi")
        bb = s.get("bb_pct")
        macd_now = s.get("macd_hist") or 0
        macd_prev = s.get("macd_prev") or 0
        rsi_str = f"{rsi:.1f}" if rsi else "-"
        bb_str = f"{bb:.1f}" if bb else "-"
        macd_up = "✅" if macd_now > 0 and macd_now > macd_prev else "❌"
        rsi_cls = ""
        if rsi:
            rsi_cls = "rsi-ok\" style=\"color:#10b981;font-weight:700" if rsi < 40 else (
                "rsi-hot\" style=\"color:#ef4444;font-weight:700" if rsi > 65 else "rsi-watch")
        if rsi and rsi < 40:
            sig = '<span class="sig-yellow">🟡 Oversold - wait MACD</span>'
        elif rsi and rsi > 70:
            sig = '<span class="sig-red">🔴 Overbought</span>'
        elif rsi and rsi < 55 and macd_now > 0:
            sig = '<span class="sig-green">🟢 OK entry</span>'
        else:
            sig = '<span class="sig-yellow">⏳ Wait</span>'
        row_style = " style=\"background:#fffbeb;\"" if rsi and rsi < 40 else ""
        etf_rows += (
            f"<div class=\"etf-row\"{row_style}>"
            f"<div><strong>{etf}</strong></div>"
            f"<div>{theme}</div>"
            f"<div class=\"{rsi_cls}\">{rsi_str}</div>"
            f"<div>{bb_str}</div>"
            f"<div>{macd_up}</div>"
            f"<div>{sig}</div>"
            f"<div style=\"font-size:10px;color:#64748b;\">{entry_note}</div></div>\n"
        )

    # ── Macro narrative section (for today tab dot-connector) ──────────────
    macro_dots = ""
    status_colors = {"green": "#10b981", "yellow": "#d97706", "red": "#ef4444"}
    for narrative, info in macro_status.items():
        color = status_colors.get(info.get("status", "yellow"), "#d97706")
        note = info.get("note", "")[:120]
        macro_dots += (
            f"<div style=\"margin-bottom:6px;\">"
            f"<span style=\"color:{color};font-weight:700;\">● {narrative}</span>"
            f" - {note}</div>"
        )

    # ── Alert bar content ──────────────────────────────────────────────────
    market_dot = "● OPEN" if market_open else "● CLOSED"
    alert_pills_html = f"<span>{market_dot} · {market_status_str} · {today}</span>\n"
    for a in alerts[:8]:
        if "PROBABLE FILL" in a or "CHECK FIDELITY" in a:
            pill_cls = "yellow"
        elif "EARNINGS" in a and "URGENT" in a:
            pill_cls = ""
        elif "BIG MOVER" in a or "EARNINGS" in a:
            pill_cls = "yellow"
        elif "BUY" in a and "CLOSE" in a:
            pill_cls = "blue"
        else:
            pill_cls = ""
        alert_pills_html += f'<span class="alert-pill {pill_cls}">{a[:100]}</span>\n'
    if not alerts:
        alert_pills_html += '<span class="alert-pill green">✅ No urgent alerts today</span>'

    # ── Macro news status for research section ─────────────────────────────
    macro_status_html = ""
    for narrative, info in macro_status.items():
        color = status_colors.get(info.get("status", "yellow"), "#d97706")
        macro_status_html += (
            f"<div style=\"padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:11px;\">"
            f"<span style=\"color:{color};font-weight:700;\">●</span> "
            f"<strong>{narrative}</strong>: {info.get('note','')[:100]}</div>"
        )

    # ── Load history + trades for performance tab ─────────────────────────
    history = []
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)

    trades = []
    if TRADES_FILE.exists():
        with open(TRADES_FILE, encoding="utf-8") as f:
            trades = json.load(f)

    return _build_html(
        today=today, market_open=market_open, market_status_str=market_status_str,
        alert_pills_html=alert_pills_html,
        roth_id=roth["id"], tod_id=tod["id"],
        roth_total=roth_total, tod_total=tod_total, grand_total=grand_total,
        roth_cash=roth.get("cash", 0), tod_cash=tod.get("cash", 0),
        roth_pos_total=roth_pos_total, roth_pos_gl=roth_pos_gl,
        tod_pos_total=tod_pos_total, tod_pos_gl=tod_pos_gl,
        roth_rows=roth_rows, tod_rows=tod_rows,
        roth_pending=roth_pending, tod_pending=tod_pending,
        today_cards=today_cards, cond_rows=cond_rows,
        macro_dots=macro_dots, macro_status_html=macro_status_html,
        div_event_rows=div_event_rows, earn_event_rows=earn_event_rows,
        etf_rows=etf_rows,
        daily_read_html=daily_read_html,
        action_items_html=action_items_html,
        history=history,
        trades=trades,
        sign=sign,
    )


def _build_html(*, today, market_open, market_status_str, alert_pills_html,
                roth_id, tod_id, roth_total, tod_total, grand_total,
                roth_cash, tod_cash, roth_pos_total, roth_pos_gl,
                tod_pos_total, tod_pos_gl,
                roth_rows, tod_rows, roth_pending, tod_pending,
                today_cards, cond_rows, macro_dots, macro_status_html,
                div_event_rows, earn_event_rows, etf_rows,
                daily_read_html, action_items_html,
                history, trades, sign) -> str:

    market_badge_color = "#10b981" if market_open else "#94a3b8"

    # ── Performance tab data ───────────────────────────────────────────────
    # Equity chart JSON arrays
    hist_dates  = [h["date"] for h in history]
    hist_total  = [h["total"] for h in history]
    hist_roth   = [h["roth"]  for h in history]
    hist_tod    = [h["tod"]   for h in history]
    chart_dates_json = json.dumps(hist_dates)
    chart_total_json = json.dumps(hist_total)
    chart_roth_json  = json.dumps(hist_roth)
    chart_tod_json   = json.dumps(hist_tod)

    # Starting value for % gain calculation
    start_total = hist_total[0]  if hist_total  else grand_total
    start_roth  = hist_roth[0]   if hist_roth   else roth_total
    start_tod   = hist_tod[0]    if hist_tod    else tod_total
    total_gain  = grand_total - start_total
    total_pct   = (total_gain / start_total * 100) if start_total else 0
    roth_gain   = roth_total - start_roth
    tod_gain    = tod_total  - start_tod

    def perf_card(label, current, gain, pct):
        color = "#10b981" if gain >= 0 else "#ef4444"
        arrow = "▲" if gain >= 0 else "▼"
        return (
            f'<div class="card" style="padding:12px 14px;">'
            f'<div style="font-size:10px;color:#94a3b8;font-weight:600;">{label}</div>'
            f'<div style="font-size:20px;font-weight:800;margin:4px 0;">${current:,.0f}</div>'
            f'<div style="font-size:11px;color:{color};font-weight:700;">'
            f'{arrow} ${gain:+,.0f} ({pct:+.1f}%) tracked period</div>'
            f'</div>'
        )

    num_tracked = len(history)
    perf_summary_cards = (
        perf_card("Grand Total", grand_total, total_gain, total_pct)
        + perf_card("ROTH IRA", roth_total, roth_gain, (roth_gain/start_roth*100) if start_roth else 0)
        + perf_card("Individual TOD", tod_total, tod_gain, (tod_gain/start_tod*100) if start_tod else 0)
        + f'<div class="card" style="padding:12px 14px;grid-column:span 3;">'
          f'<div style="font-size:10px;color:#94a3b8;">'
          f'Tracking started {hist_dates[0] if hist_dates else today} · {num_tracked} data points · '
          f'Updates every morning run</div></div>'
    )

    # Trades table rows
    trades_rows = ""
    realized_total = 0.0
    for tr in reversed(trades):  # newest first
        pl  = tr.get("pl_dollar", 0)
        pct = tr.get("pl_pct", 0)
        realized_total += pl
        color = "#10b981" if pl >= 0 else "#ef4444"
        trades_rows += (
            f'<tr style="border-bottom:1px solid #f1f5f9;">'
            f'<td style="padding:6px 8px;font-size:11px;color:#64748b;">{tr.get("date","")}</td>'
            f'<td style="padding:6px;font-weight:700;font-size:12px;">{tr.get("ticker","")}</td>'
            f'<td style="padding:6px;font-size:10px;color:#64748b;">{tr.get("account","")}</td>'
            f'<td style="padding:6px;text-align:right;font-size:11px;">{tr.get("shares","")}</td>'
            f'<td style="padding:6px;text-align:right;font-size:11px;">${tr.get("avg_cost",0):.2f}</td>'
            f'<td style="padding:6px;text-align:right;font-size:11px;">${tr.get("sell_price",0):.2f}</td>'
            f'<td style="padding:6px;text-align:right;font-size:11px;color:{color};font-weight:700;">${pl:+.0f}</td>'
            f'<td style="padding:6px;text-align:right;font-size:11px;color:{color};font-weight:700;">{pct:+.1f}%</td>'
            f'<td style="padding:6px;text-align:right;font-size:11px;color:#94a3b8;">{tr.get("hold_days","-")}d</td>'
            f'</tr>'
        )
    if not trades_rows:
        trades_rows = '<tr><td colspan="9" style="padding:16px;text-align:center;color:#94a3b8;font-size:12px;">No closed trades yet - sell a position to record it here</td></tr>'
    else:
        rl_color = "#10b981" if realized_total >= 0 else "#ef4444"
        trades_rows += (
            f'<tr style="background:#f8fafc;font-weight:700;">'
            f'<td colspan="6" style="padding:8px;font-size:11px;">Total Realized P&L</td>'
            f'<td style="padding:8px;text-align:right;font-size:12px;color:{rl_color};">${realized_total:+.0f}</td>'
            f'<td colspan="2"></td></tr>'
        )

    CSS = """
:root{color-scheme:light;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#1a1a2e;font-size:13px;}
.alert-bar{background:#1a1a2e;color:white;padding:8px 20px;font-size:12px;font-weight:700;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.alert-pill{color:white;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700;background:#ef4444;}
.alert-pill.green{background:#10b981;}.alert-pill.blue{background:#3b82f6;}.alert-pill.yellow{background:#d97706;}.alert-pill.purple{background:#8b5cf6;}
.header{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);color:white;padding:14px 20px;}
.header h1{font-size:17px;font-weight:700;}.header-meta{font-size:11px;color:#94a3b8;margin-top:2px;}
.header-stats{display:flex;gap:20px;margin-top:10px;flex-wrap:wrap;}
.stat-label{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;}
.stat-value{font-size:18px;font-weight:700;color:white;}
.stat-sub{font-size:11px;color:#4ade80;}.stat-sub.red{color:#f87171;}
.tabs{display:flex;background:white;border-bottom:2px solid #e2e8f0;padding:0 20px;gap:2px;overflow-x:auto;}
.tab{padding:9px 14px;cursor:pointer;font-size:11px;font-weight:600;color:#64748b;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all 0.15s;white-space:nowrap;}
.tab.active{color:#1a1a2e;border-bottom-color:#16213e;}.tab:hover:not(.active){color:#334155;}
.content{display:none;padding:14px 20px;}.content.active{display:block;}
.section-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#64748b;margin-bottom:8px;margin-top:16px;display:flex;align-items:center;gap:6px;}
.section-title:first-child{margin-top:0;}
.badge{color:white;font-size:9px;padding:2px 6px;border-radius:10px;background:#475569;}
.card{background:white;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:10px;}
table{width:100%;border-collapse:collapse;}
th{background:#f8fafc;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#94a3b8;padding:7px 10px;text-align:left;border-bottom:1px solid #e2e8f0;}
td{padding:8px 10px;border-bottom:1px solid #f1f5f9;vertical-align:middle;}
tr:last-child td{border-bottom:none;}tr:hover td{background:#f8fafc;}
.sym{font-weight:700;font-size:13px;color:#1a1a2e;}.sym-name{font-size:10px;color:#94a3b8;}
.gl-pos{color:#10b981;font-weight:600;}.gl-neg{color:#ef4444;font-weight:600;}
.t-swing{background:#dbeafe;color:#1d4ed8;font-size:9px;padding:2px 6px;border-radius:8px;font-weight:700;}
.t-long{background:#dcfce7;color:#166534;font-size:9px;padding:2px 6px;border-radius:8px;font-weight:700;}
.t-income{background:#fef3c7;color:#92400e;font-size:9px;padding:2px 6px;border-radius:8px;font-weight:700;}
.t-life{background:#f3e8ff;color:#6b21a8;font-size:9px;padding:2px 6px;border-radius:8px;font-weight:700;}
.t-spec{background:#fee2e2;color:#991b1b;font-size:9px;padding:2px 6px;border-radius:8px;font-weight:700;}
.t-etf{background:#e0f2fe;color:#0369a1;font-size:9px;padding:2px 6px;border-radius:8px;font-weight:700;}
.orders-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.order-card{background:white;border-radius:8px;padding:11px;box-shadow:0 1px 3px rgba(0,0,0,0.08);border-left:3px solid #3b82f6;}
.order-card.done{border-left-color:#10b981;background:#f0fdf4;}.order-card.warn{border-left-color:#f59e0b;background:#fffbeb;}.order-card.tod{border-left-color:#10b981;}
.order-sym{font-weight:700;font-size:14px;}.order-detail{font-size:11px;color:#64748b;margin-top:2px;}.order-price{font-size:15px;font-weight:700;margin-top:5px;}.order-status{font-size:10px;margin-top:3px;font-weight:600;}
.event-list{display:flex;flex-direction:column;gap:6px;}
.event{background:white;border-radius:8px;padding:9px 12px;box-shadow:0 1px 3px rgba(0,0,0,0.08);display:flex;gap:10px;}
.event-day{font-size:10px;font-weight:700;color:white;background:#1a1a2e;border-radius:6px;padding:4px 7px;min-width:44px;text-align:center;flex-shrink:0;}
.event-day.today{background:#ef4444;}.event-day.warn{background:#d97706;}.event-day.done{background:#10b981;}
.event-title{font-weight:600;font-size:12px;}.event-sub{font-size:11px;color:#64748b;margin-top:2px;line-height:1.4;}
.tag{display:inline-block;font-size:9px;padding:1px 5px;border-radius:3px;font-weight:700;margin-right:3px;}
.tag-hold{background:#fef3c7;color:#92400e;}.tag-watch{background:#dbeafe;color:#1d4ed8;}.tag-buy{background:#dcfce7;color:#166534;}.tag-done{background:#dcfce7;color:#166534;}
.trump-row{display:grid;grid-template-columns:1fr 1fr 80px;padding:9px 12px;border-bottom:1px solid #f1f5f9;align-items:center;gap:10px;background:white;}
.trump-row:last-child{border-bottom:none;}.trump-row.hdr{background:#f8fafc;font-size:10px;font-weight:700;text-transform:uppercase;color:#94a3b8;border-radius:10px 10px 0 0;}
.trump-wrap{border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);}
.dir-buy{color:#10b981;font-weight:700;font-size:11px;}.dir-sell{color:#ef4444;font-weight:700;font-size:11px;}
.rule-box{background:#1a1a2e;color:white;border-radius:10px;padding:12px 14px;margin-bottom:8px;}
.rule-box h3{font-size:11px;font-weight:700;color:#4ade80;margin-bottom:6px;}
.rule-item{font-size:11px;color:#94a3b8;padding:3px 0;border-bottom:1px solid #0f172a;display:flex;gap:7px;}
.rule-item:last-child{border-bottom:none;}.rule-num{color:#4ade80;font-weight:700;flex-shrink:0;}
.cash-bar{background:white;border-radius:10px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:10px;}
.sector-row{display:grid;grid-template-columns:140px 50px 1fr 1fr 80px;padding:8px 12px;border-bottom:1px solid #f1f5f9;align-items:center;gap:8px;background:white;font-size:11px;}
.sector-row.hdr{background:#f8fafc;font-size:10px;font-weight:700;text-transform:uppercase;color:#94a3b8;}
.sector-row:last-child{border-bottom:none;}
.sector-wrap{border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:10px;}
.s-ok{color:#10b981;font-weight:700;font-size:11px;}.s-warn{color:#d97706;font-weight:700;font-size:11px;}.s-gap{color:#ef4444;font-weight:700;font-size:11px;}
.geo-card{background:white;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:12px;overflow:hidden;}
.geo-header{padding:12px 14px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #f1f5f9;}
.geo-flag{font-size:20px;}.geo-title{font-weight:700;font-size:13px;}.geo-sub{font-size:10px;color:#64748b;margin-top:1px;}
.geo-urgency{font-size:9px;padding:2px 7px;border-radius:8px;font-weight:700;margin-left:auto;}
.urgency-high{background:#fee2e2;color:#991b1b;}.urgency-med{background:#fef3c7;color:#92400e;}.urgency-low{background:#dcfce7;color:#166534;}
.geo-body{padding:0 14px 12px;}
.signal-row{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:6px 0;border-bottom:1px solid #f8fafc;font-size:11px;}
.signal-row:last-child{border-bottom:none;}.sig-buy{color:#10b981;font-weight:600;}.sig-sell{color:#ef4444;font-weight:600;}.sig-watch{color:#d97706;font-weight:600;}
.geo-key{background:#f8fafc;border-radius:6px;padding:8px 10px;margin-top:8px;font-size:10px;color:#64748b;line-height:1.5;}
.geo-key strong{color:#1a1a2e;}
.theme-card{background:white;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:12px;overflow:hidden;}
.theme-header{padding:12px 14px;background:linear-gradient(135deg,#1a1a2e,#1e3a5f);color:white;display:flex;align-items:center;gap:10px;}
.theme-icon{font-size:22px;}.theme-title{font-weight:700;font-size:14px;}.theme-horizon{font-size:10px;color:#94a3b8;margin-top:1px;}
.theme-body{padding:12px 14px;}
.theme-key-fact{background:#fffbeb;border-left:3px solid #d97706;padding:8px 10px;border-radius:0 6px 6px 0;font-size:11px;color:#374151;margin-bottom:10px;line-height:1.5;}
.theme-key-fact strong{color:#92400e;}
.theme-plays{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;}
.theme-play{border-radius:6px;padding:8px 10px;font-size:11px;}
.play-own{background:#f0fdf4;border:1px solid #bbf7d0;}.play-watch{background:#eff6ff;border:1px solid #bfdbfe;}.play-wait{background:#f5f5f5;border:1px solid #e5e5e5;}
.play-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;}
.own-label{color:#166534;}.watch-label{color:#1d4ed8;}.wait-label{color:#6b7280;}
.play-sym{font-weight:700;font-size:12px;}.play-note{font-size:10px;color:#6b7280;margin-top:1px;}
.etf-row{display:grid;grid-template-columns:70px 1fr 55px 55px 50px 90px 120px;padding:8px 12px;border-bottom:1px solid #f1f5f9;align-items:center;gap:6px;background:white;font-size:11px;}
.etf-row.hdr{background:#f8fafc;font-size:10px;font-weight:700;text-transform:uppercase;color:#94a3b8;}
.etf-row:last-child{border-bottom:none;}
.etf-wrap{border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:10px;}
.rsi-hot{color:#ef4444;font-weight:700;}.rsi-ok{color:#10b981;font-weight:700;}.rsi-watch{color:#d97706;font-weight:700;}
.sig-green{background:#dcfce7;color:#166534;padding:2px 7px;border-radius:8px;font-size:10px;font-weight:700;}
.sig-yellow{background:#fef3c7;color:#92400e;padding:2px 7px;border-radius:8px;font-size:10px;font-weight:700;}
.sig-red{background:#fee2e2;color:#991b1b;padding:2px 7px;border-radius:8px;font-size:10px;font-weight:700;}
.source-row{display:grid;grid-template-columns:150px 1fr 100px;padding:8px 12px;border-bottom:1px solid #f1f5f9;align-items:center;gap:8px;background:white;font-size:11px;}
.source-row.hdr{background:#f8fafc;font-size:10px;font-weight:700;text-transform:uppercase;color:#94a3b8;}
.source-row:last-child{border-bottom:none;}
.source-wrap{border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:10px;}
.lag-fast{color:#10b981;font-weight:600;font-size:10px;}.lag-mid{color:#d97706;font-weight:600;font-size:10px;}.lag-slow{color:#6b7280;font-size:10px;}
.conf-row{display:grid;grid-template-columns:110px 1fr 1fr;padding:8px 12px;border-bottom:1px solid #f1f5f9;align-items:center;gap:8px;background:white;font-size:11px;}
.conf-row.hdr{background:#f8fafc;font-size:10px;font-weight:700;text-transform:uppercase;color:#94a3b8;}
.conf-row:last-child{border-bottom:none;}
.conf-wrap{border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:10px;}
.type-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;}
.type-card{border-radius:8px;padding:10px 12px;border:1px solid #e2e8f0;background:white;}
.type-badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:8px;display:inline-block;margin-bottom:6px;}
.type-name{font-weight:700;font-size:12px;margin-bottom:4px;}
.type-detail{font-size:10px;color:#64748b;line-height:1.5;}
.updated-note{text-align:center;font-size:10px;color:#94a3b8;padding:8px;}
.hl-green td{background:#f0fdf4!important;}.hl-warn td{background:#fff7ed!important;}.hl-new td{background:#eff6ff!important;}.hl-gold td{background:#fffbeb!important;}.hl-purple td{background:#faf5ff!important;}
@media(max-width:768px){
  body{font-size:12px;}
  .header{padding:12px 14px;}
  .header-stats{grid-template-columns:1fr 1fr;gap:8px;}
  .stat-value{font-size:18px;}
  .tabs{padding:0 10px;}
  .tab{padding:8px 10px;font-size:10px;}
  .content{padding:10px 12px;}
  .orders-grid{grid-template-columns:1fr;}
  table{font-size:11px;}
  th,td{padding:5px 6px;}
  .type-grid{grid-template-columns:1fr;}
  .geo-grid{grid-template-columns:1fr!important;}
  .theme-grid{grid-template-columns:1fr!important;}
}
@media(max-width:480px){
  .header-stats{grid-template-columns:1fr;}
  .stat-value{font-size:16px;}
}
"""

    # ── STATIC SECTIONS (Geo, Themes, Sectors, Trump, Research, Rules) ────
    GEO_TAB = """
<div class="geo-key" style="margin-bottom:12px;font-size:11px;line-height:1.6;"><strong>🌍 The Alpha Layer Most Retail Investors Skip Entirely.</strong> Geopolitical signals move markets 48-72 hours before they're obvious on CNBC. The frameworks below map each flashpoint to specific trades.</div>

<div class="geo-card">
  <div class="geo-header"><div class="geo-flag">🕌🔥</div><div><div class="geo-title">Iran War - Middle East Energy Crisis</div><div class="geo-sub">Active since Feb 28 2026 · Hormuz disrupted · Qatar LNG offline · UAE exits OPEC May 1</div></div><div class="geo-urgency urgency-high">🔴 ACTIVE WAR</div></div>
  <div class="geo-body">
    <div class="geo-key"><strong>What's confirmed:</strong> US strikes on Iranian nuclear/military sites started Feb 28. Strait of Hormuz disrupted. Qatar LNG export facility damaged - 12.8 MTPA offline 3-5 years. Global oil supply dropped 10.1 mb/d in March. UAE exiting OPEC May 1. EPD Q1 directly credited Iran war: "Increased demand for US energy exports amid Middle East disruptions." Revenue $14.39B beat.</div>
    <div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;margin:10px 0 6px;">Signal → Trade Map</div>
    <div class="signal-row"><div class="signal-trigger">🚨 Escalation / Hormuz deepens</div><div class="signal-action sig-buy">BUY EPD, ET, GLD, RTX, ITA same day</div></div>
    <div class="signal-row"><div class="signal-trigger">✅ Peace deal / Hormuz reopens</div><div class="signal-action sig-watch">Review EPD thesis (still OK - volume play). SELL GLD partially. BUY airlines.</div></div>
    <div class="signal-row"><div class="signal-trigger">🚨 New US strikes on Iran</div><div class="signal-action sig-buy">BUY GLD immediately. Defense holds.</div></div>
    <div class="geo-key" style="margin-top:10px;"><strong>Portfolio exposure:</strong> EPD (ROTH ✅ direct - Q1 confirmed) · GLD (ROTH ✅ hedge) · RTX (ROTH ✅ defense) · ITA (watch - oversold defense ETF in active war)</div>
  </div>
</div>

<div class="geo-card">
  <div class="geo-header"><div class="geo-flag">🇨🇳🇺🇸</div><div><div class="geo-title">US-China Decoupling</div><div class="geo-sub">Rare earth weaponization · Semiconductor war · Taiwan risk</div></div><div class="geo-urgency urgency-high">🔴 ACTIVE NOW</div></div>
  <div class="geo-body">
    <div class="geo-key"><strong>Key fact:</strong> China controls 85-90% of global rare earth processing. In 2026, China began restricting dysprosium and terbium exports. MP Materials = only US-scale producer. TSMC needs rare earths for every &lt;5nm chip.</div>
    <div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;margin:10px 0 6px;">Signal → Trade Map</div>
    <div class="signal-row"><div class="signal-trigger">🚨 China tightens RE export quotas</div><div class="signal-action sig-buy">BUY MP aggressively, REMX</div></div>
    <div class="signal-row"><div class="signal-trigger">🚨 Taiwan Strait incident</div><div class="signal-action sig-buy">BUY GLD, EPD, RTX, NOC · SELL TSM, ASML</div></div>
    <div class="signal-row"><div class="signal-trigger">✅ US-China trade deal signed</div><div class="signal-action sig-sell">BUY TSM, ASML, SMH · SELL GLD</div></div>
    <div class="geo-key" style="margin-top:10px;"><strong>Portfolio exposure:</strong> MP (ROTH ✅ direct play) · TSM at ~12% TOD = at limit - do NOT add · RTX, NOC = defense hedge ✅ · GLD = macro hedge ✅</div>
  </div>
</div>

<div class="geo-card">
  <div class="geo-header"><div class="geo-flag">🇪🇺🛡️</div><div><div class="geo-title">Europe Rearmament Supercycle</div><div class="geo-sub">NATO 5% GDP target · €800B EU mobilization · 10-year structural trade</div></div><div class="geo-urgency urgency-high">🔴 STRUCTURAL - 10YR</div></div>
  <div class="geo-body">
    <div class="geo-key"><strong>Key fact:</strong> Global military spending hit $2.89 TRILLION in 2025. EU plans €800B by 2030. NATO targeting 5% GDP (up from 2%). Rheinmetall: +45% revenue in 2026, 9.5 YEARS of backlog. This spending does NOT stop regardless of who's in power.</div>
    <div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;margin:10px 0 6px;">Signal → Trade Map</div>
    <div class="signal-row"><div class="signal-trigger">🚨 Russia escalates (new front)</div><div class="signal-action sig-buy">BUY ITA, RTX, NOC, KTOS immediately</div></div>
    <div class="signal-row"><div class="signal-trigger">✅ Ukraine ceasefire</div><div class="signal-action sig-buy">Defense dip = BUY - rearmament continues regardless</div></div>
    <div class="signal-row"><div class="signal-trigger">🚨 US reduces NATO commitment</div><div class="signal-action sig-buy">BUY European defense (they spend MORE when US pulls back)</div></div>
    <div class="geo-key" style="margin-top:10px;"><strong>⭐ Active Iran war + Europe rearmament = defense bull market with no end date in sight. RTX + NOC = full ROTH defense. ITA ETF = next add in TOD.</strong></div>
  </div>
</div>

<div class="geo-card">
  <div class="geo-header"><div class="geo-flag">🌐💰</div><div><div class="geo-title">BRICS De-Dollarization</div><div class="geo-sub">USD reserve share declining · Central banks buying gold at record pace</div></div><div class="geo-urgency urgency-low">🟢 SLOW BURN 5-10YR</div></div>
  <div class="geo-body">
    <div class="geo-key"><strong>Key fact:</strong> Russia, China, India, Brazil, Saudi Arabia all reducing USD transaction share. Central banks buying gold at record rates. USD global reserve share declining. Rubio (US Sec of State) confirmed de-dollarization is accelerating. GLD is the neutral reserve asset no government controls.</div>
    <div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;margin:10px 0 6px;">Signal → Trade Map</div>
    <div class="signal-row"><div class="signal-trigger">🚨 Major oil deal priced in yuan</div><div class="signal-action sig-buy">BUY GLD aggressively</div></div>
    <div class="signal-row"><div class="signal-trigger">🚨 Fed cuts aggressively</div><div class="signal-action sig-buy">BUY GLD, EPD, real assets</div></div>
    <div class="signal-row"><div class="signal-trigger">⚠️ Dollar strengthens sharply</div><div class="signal-action sig-watch">Watch GLD - may trim if RSI &gt; 75</div></div>
  </div>
</div>

<div class="geo-card">
  <div class="geo-header"><div class="geo-flag">🏦⚠️</div><div><div class="geo-title">Trump Fed / Bond Vigilante Risk</div><div class="geo-sub">Politically-motivated rate cuts · Inflation stays elevated · Bond market rebels</div></div><div class="geo-urgency urgency-high">🔴 HIGH RISK - 2026-2027</div></div>
  <div class="geo-body">
    <div class="geo-key"><strong>The scenario:</strong> Trump appoints a compliant Fed chair. New chair cuts rates even at 3%+ inflation. Bond market doesn't trust it - bond vigilantes sell Treasuries, yields RISE despite Fed cutting. Worst of both worlds: loose monetary policy + rising long-term rates + persistent inflation.</div>
    <div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;margin:10px 0 6px;">Signal → Trade Map</div>
    <div class="signal-row"><div class="signal-trigger">🚨 Trump announces dovish Fed chair pick</div><div class="signal-action sig-buy">BUY GLD aggressively. Real rates going negative = gold's best environment.</div></div>
    <div class="signal-row"><div class="signal-trigger">🚨 Fed cuts but 10yr yield RISES anyway</div><div class="signal-action sig-buy">Bond vigilante confirmed. MAX GLD. Hold EPD. Trim bonds.</div></div>
    <div class="signal-row"><div class="signal-trigger">📊 CPI re-accelerates above 4% after cut</div><div class="signal-action sig-buy">BUY GLD, EPD, commodities. TRIM tech growth multiples.</div></div>
    <div class="geo-key" style="margin-top:10px;"><strong>Portfolio positioned for this:</strong> GLD ✅ best in negative real rates · EPD ✅ real infrastructure, inflation-resistant · RTX/NOC ✅ govt spending, immune to monetary policy</div>
  </div>
</div>
"""

    THEMES_TAB = """
<div class="geo-key" style="margin-bottom:12px;font-size:11px;line-height:1.6;"><strong>🚀 The Next SOXX Plays.</strong> Each theme below is at an early stage. Research now, buy when RSI/MACD gives the entry signal.</div>

<div class="theme-card">
  <div class="theme-header"><div class="theme-icon">🤖</div><div><div class="theme-title">Humanoid Robots - Physical AI</div><div class="theme-horizon">2026-2030 inflection · Morgan Stanley: $38B by 2035, $5T by 2050</div></div></div>
  <div class="theme-body">
    <div class="theme-key-fact"><strong>Key fact most miss:</strong> Manufacturing cost dropped 40% in ONE YEAR (2023→2024). Tesla targeting 50,000 Optimus units in 2026. NVIDIA Isaac platform = the "Android OS" for every humanoid robot. TAM = 5 billion units at $20K = $100T.</div>
    <div class="theme-plays">
      <div class="theme-play play-own"><div class="play-label own-label">Already Own ✅</div><div class="play-sym">NVDA</div><div class="play-note">Isaac robotics platform. Every humanoid robot runs on it.</div></div>
      <div class="theme-play play-own"><div class="play-label own-label">Already Own ✅</div><div class="play-sym">MSFT</div><div class="play-note">Invested in Figure AI. Azure = robot cloud.</div></div>
      <div class="theme-play play-watch"><div class="play-label watch-label">Watch 👀</div><div class="play-sym">BOTZ ETF</div><div class="play-note">Wait for RSI &lt; 45 before entry. ~$500 TOD.</div></div>
      <div class="theme-play play-wait"><div class="play-label wait-label">Future IPO 🔮</div><div class="play-sym">Figure AI</div><div class="play-note">Private. When IPO - immediate research. Could be the NVDA of robotics.</div></div>
    </div>
  </div>
</div>

<div class="theme-card">
  <div class="theme-header" style="background:linear-gradient(135deg,#1a2e1a,#1a3e1a);"><div class="theme-icon">⚛️</div><div><div class="theme-title">Nuclear Energy Renaissance</div><div class="theme-horizon">2026-2035 structural · AI data centers need 24/7 baseload power</div></div></div>
  <div class="theme-body">
    <div class="theme-key-fact"><strong>Key fact most miss:</strong> Every big tech company signing nuclear PPAs because renewables are intermittent. Microsoft: 20-yr $1.6B Three Mile Island deal. Google + Kairos 500MW SMR. Amazon: 5GW X-energy by 2039. Meta RFP for 1-4GW. 2026 = 15 new reactors globally.</div>
    <div class="theme-plays">
      <div class="theme-play play-own"><div class="play-label own-label">Indirect ✅</div><div class="play-sym">MSFT / GOOGL / AMZN</div><div class="play-note">All signing nuclear PPAs. Benefit from cheap clean power.</div></div>
      <div class="theme-play play-watch"><div class="play-label watch-label">Buy Now 👀</div><div class="play-sym">CCJ - Cameco</div><div class="play-note">Every new PPA = CCJ goes up. 1-2sh TOD.</div></div>
      <div class="theme-play play-watch"><div class="play-label watch-label">Watch ⏳</div><div class="play-sym">NUCL ETF</div><div class="play-note">Wait for pullback below RSI 50. Then $500 TOD.</div></div>
      <div class="theme-play play-wait"><div class="play-label wait-label">Speculative 🎰</div><div class="play-sym">OKLO</div><div class="play-note">Wait for big pullback. RSI overbought.</div></div>
    </div>
    <div class="geo-key" style="margin-top:10px;">📡 Watch: IAEA bulletins, World Nuclear Association reports, any new tech company nuclear PPA → CCJ buy trigger.</div>
  </div>
</div>

<div class="theme-card">
  <div class="theme-header" style="background:linear-gradient(135deg,#2e1a0a,#3e2a0a);"><div class="theme-icon">🪨</div><div><div class="theme-title">Rare Earth / Critical Minerals</div><div class="theme-horizon">NOW - China weaponizing. MP is the only play.</div></div></div>
  <div class="theme-body">
    <div class="theme-key-fact"><strong>Key fact most miss:</strong> Rare earths inside every EV motor, F-35, smartphone, MRI machine, and semiconductor fab. China controls 85-90% of processing and restricting exports of dysprosium and terbium in 2026. MP Materials = first US-made permanent magnets since the 1980s. NDAA contracts guaranteed.</div>
    <div class="theme-plays">
      <div class="theme-play play-own"><div class="play-label own-label">Direct Play ✅</div><div class="play-sym">MP Materials</div><div class="play-note">ROTH 7sh. China restriction = immediate catalyst.</div></div>
      <div class="theme-play play-own"><div class="play-label own-label">Indirect ✅</div><div class="play-sym">RTX / NOC</div><div class="play-note">Defense sector. RE shortages strengthen domestic supplier position.</div></div>
      <div class="theme-play play-watch"><div class="play-label watch-label">ETF Option ⏳</div><div class="play-sym">REMX</div><div class="play-note">MP covers thesis for now.</div></div>
      <div class="theme-play play-wait"><div class="play-label wait-label">Watch 🔮</div><div class="play-sym">USA Rare Earth</div><div class="play-note">Private. If IPO → immediate research.</div></div>
    </div>
    <div class="geo-key" style="margin-top:10px;">📡 Watch: China MOFCOM announcements. Any new RE export restriction → BUY MP same day, no waiting for RSI.</div>
  </div>
</div>

<div class="theme-card">
  <div class="theme-header" style="background:linear-gradient(135deg,#0a1a2e,#0a2a3e);"><div class="theme-icon">🤝</div><div><div class="theme-title">Agentic AI Infrastructure</div><div class="theme-horizon">2025-2028 enterprise wave · Already owning the right plays</div></div></div>
  <div class="theme-body">
    <div class="theme-key-fact"><strong>Key fact most miss:</strong> Wave 1 of AI = ChatGPT (consumer). Wave 2 = AI agents running inside enterprises. Salesforce has 25 years of irreplaceable CRM data. Agentforce ARR: $800M, up 169% YoY. AI doesn't kill CRM - it makes the data MORE valuable.</div>
    <div class="theme-plays">
      <div class="theme-play play-own"><div class="play-label own-label">Direct Play ✅</div><div class="play-sym">CRM</div><div class="play-note">ROTH 12sh. Agentforce is the enterprise AI OS.</div></div>
      <div class="theme-play play-own"><div class="play-label own-label">Infrastructure ✅</div><div class="play-sym">MSFT / GOOGL / AMZN</div><div class="play-note">Azure, Google Cloud, AWS = the pipes agents run on.</div></div>
      <div class="theme-play play-watch"><div class="play-label watch-label">Research Needed 👀</div><div class="play-sym">PLTR</div><div class="play-note">Govt AI + defense agentic AI. Deep dive before entering.</div></div>
      <div class="theme-play play-watch"><div class="play-label watch-label">Watch 👀</div><div class="play-sym">NOW (ServiceNow)</div><div class="play-note">Pure agentic AI play. Research valuation before entering.</div></div>
    </div>
    <div class="geo-key" style="margin-top:10px;">📡 Watch: Earnings call language from MSFT, GOOGL, AMZN. When all 3 use the same new word in the same quarter → that word is the next trade.</div>
  </div>
</div>
"""

    SECTORS_TAB = """
<div class="section-title">🗂 Sector Map - Both Accounts</div>
<div class="sector-wrap">
  <div class="sector-row hdr"><div>Sector</div><div>ETF</div><div>ROTH IRA</div><div>Individual TOD</div><div>Status</div></div>
  <div class="sector-row" style="background:#fee2e2;"><div><strong>Defense</strong></div><div>ITA</div><div>RTX, NOC ★filled</div><div>- (ITA next)</div><div class="s-warn">⚠️ 2/2 MAX</div></div>
  <div class="sector-row"><div><strong>Technology</strong></div><div>XLK</div><div>CRM</div><div>ASML, AMD, TSM, NVDA, AAPL, MSFT, BBAI</div><div class="s-warn">⚠️ TOD heavy</div></div>
  <div class="sector-row"><div><strong>Comm Services</strong></div><div>XLC</div><div>-</div><div>META, GOOGL, NFLX</div><div class="s-warn">⚠️ Concentrated</div></div>
  <div class="sector-row"><div><strong>Healthcare</strong></div><div>XLV</div><div>MDT</div><div>NVO (pending)</div><div class="s-ok">✅ Good</div></div>
  <div class="sector-row"><div><strong>Energy / MLP</strong></div><div>XLE</div><div>EPD</div><div>-</div><div class="s-ok">✅ Iran war tailwind</div></div>
  <div class="sector-row"><div><strong>Materials / RE</strong></div><div>REMX</div><div>MP</div><div>-</div><div class="s-ok">✅ Good</div></div>
  <div class="sector-row"><div><strong>Consumer Staples</strong></div><div>XLP</div><div>BJ</div><div>-</div><div class="s-ok">✅ Recession hedge</div></div>
  <div class="sector-row"><div><strong>Macro Hedge</strong></div><div>GLD</div><div>GLD</div><div>-</div><div class="s-ok">✅ Lifetime</div></div>
  <div class="sector-row" style="background:#fee2e2;"><div><strong>Financials</strong></div><div>XLF</div><div>❌ NONE</div><div>❌ NONE</div><div class="s-gap">🚨 GAP - fill V or BRK-B</div></div>
  <div class="sector-row"><div><strong>Consumer Disc</strong></div><div>XLY</div><div>NKE</div><div>AMZN</div><div class="s-ok">✅ Fine</div></div>
  <div class="sector-row"><div><strong>Nuclear</strong></div><div>NUCL</div><div>-</div><div>CCJ (future)</div><div class="s-warn">⏳ Watching</div></div>
  <div class="sector-row"><div><strong>Robotics/AI HW</strong></div><div>BOTZ</div><div>-</div><div>BOTZ (future)</div><div class="s-warn">⏳ Wait RSI &lt;45</div></div>
</div>
<div class="rule-box">
  <h3>Sector Rules</h3>
  <div class="rule-item"><span class="rule-num">1.</span>Max 2 positions per sector per account. No exceptions.</div>
  <div class="rule-item"><span class="rule-num">2.</span>ROTH defense: RTX + NOC = 2 = AT MAX. No GD or ITA in ROTH until one exits.</div>
  <div class="rule-item"><span class="rule-num">3.</span>TOD tech + comm services ~71% = intentional secular AI bet. FREEZE new tech adds until financials filled.</div>
  <div class="rule-item"><span class="rule-num">4.</span>TSM limit: never exceed 10% of TOD. Monitor monthly.</div>
  <div class="rule-item"><span class="rule-num">5.</span>Fill priority: Financials (V or BRK-B) → Healthcare depth (ISRG) → Nuclear (CCJ).</div>
</div>
"""

    TRUMP_TAB = """
<div class="section-title">⚡ Trump Signal Framework</div>
<div class="trump-wrap">
  <div class="trump-row hdr"><div>Signal</div><div>Action</div><div>Speed</div></div>
  <div class="trump-row"><div>Tariff threat on country X</div><div class="dir-buy">Avoid importers · buy domestic alternatives</div><div style="font-size:10px;color:#d97706;">Same day</div></div>
  <div class="trump-row"><div>Tariff pause / trade deal</div><div class="dir-buy">BUY tech, consumer disc, TSM, ASML</div><div style="font-size:10px;color:#ef4444;">Immediate</div></div>
  <div class="trump-row"><div>Iran escalation language</div><div class="dir-buy">BUY EPD, GLD, RTX, NOC same day</div><div style="font-size:10px;color:#ef4444;">Immediate</div></div>
  <div class="trump-row"><div>Iran peace deal hints</div><div class="dir-sell">SELL energy/gold/defense · BUY airlines</div><div style="font-size:10px;color:#ef4444;">Immediate</div></div>
  <div class="trump-row"><div>Rare earth executive order</div><div class="dir-buy">BUY MP aggressively - no waiting</div><div style="font-size:10px;color:#ef4444;">Immediate</div></div>
  <div class="trump-row"><div>50%+ tariff on China</div><div class="dir-buy">BUY INTC, AVGO domestic semis · SELL importers</div><div style="font-size:10px;color:#ef4444;">Immediate</div></div>
  <div class="trump-row"><div>Government equity stake</div><div class="dir-buy">BUY that company - govt won't let it fail</div><div style="font-size:10px;color:#d97706;">Same day</div></div>
  <div class="trump-row"><div>NATO criticism / pull back</div><div class="dir-buy">BUY European defense (they spend MORE when US pulls back)</div><div style="font-size:10px;color:#d97706;">Same day</div></div>
  <div class="trump-row"><div>Nuclear EO / SMR fast-track</div><div class="dir-buy">BUY CCJ, OKLO, NUCL ETF</div><div style="font-size:10px;color:#d97706;">Same day</div></div>
  <div class="trump-row"><div>Social media pump (no policy doc)</div><div class="dir-sell">DO NOT TRADE. Wait 48h for policy confirmation.</div><div style="font-size:10px;color:#6b7280;">48hr wait</div></div>
</div>
<div class="rule-box" style="margin-top:12px;">
  <h3>Government-Backed - Do NOT Short These</h3>
  <div class="rule-item"><span class="rule-num">🛡️</span>NVDA, INTC, AMD, MP Materials - government has skin in the game. Shorting = fighting the US government.</div>
  <div class="rule-item"><span class="rule-num">📜</span>The Spirit Airlines Template: struggling companies in politically sensitive sectors get Trump intervention. Signal on Truth Social 12-48hrs before official.</div>
</div>
"""

    RESEARCH_TAB = """
<div class="section-title">🔬 Intelligence Sources - Where to Find Alpha First</div>
<div class="geo-key" style="margin-bottom:10px;">The edge comes from understanding what's going to matter BEFORE the crowd. By the time it's on CNBC, it's too late.</div>
<div class="source-wrap">
  <div class="source-row hdr"><div>Source</div><div>What to Watch</div><div>Signal Lead</div></div>
  <div class="source-row"><div><strong>NVIDIA GTC</strong> (annual March)</div><div>Jensen's keynote = 2-year market roadmap. "Physical AI" 2025 = buy robotics.</div><div class="lag-fast">0 days - act now</div></div>
  <div class="source-row"><div><strong>arXiv.org</strong> (cs.AI, quant-ph)</div><div>Research papers before they become products. "Attention Is All You Need" → NVDA run.</div><div class="lag-mid">12-18 months early</div></div>
  <div class="source-row"><div><strong>Truth Social / X (Trump)</strong></div><div>Tariff, trade, executive action hints. Always 12-48hrs before official announcement.</div><div class="lag-fast">12-48 hours early</div></div>
  <div class="source-row"><div><strong>IAEA Bulletins</strong></div><div>Nuclear deals, new reactor capacity. Every new deal → CCJ goes up.</div><div class="lag-mid">1-3 months early</div></div>
  <div class="source-row"><div><strong>Congressional NDAA markup</strong></div><div>Defense contract winners revealed before public. RTX, NOC, KTOS hidden in footnotes.</div><div class="lag-mid">6-12 months early</div></div>
  <div class="source-row"><div><strong>Earnings call transcripts</strong></div><div>CEO word changes signal pivots. When MSFT, GOOGL, AMZN all use same new word → that's the trade.</div><div class="lag-mid">1-2 quarters early</div></div>
  <div class="source-row"><div><strong>China MOFCOM</strong></div><div>Rare earth export restriction announcements. Any new RE restriction → BUY MP same day.</div><div class="lag-fast">0 days - act now</div></div>
</div>
<div class="section-title">🎥 YouTube / Podcast Alpha Stack</div>
<div class="source-wrap">
  <div class="source-row hdr"><div>Creator</div><div>Best For</div><div>Use Case</div></div>
  <div class="source-row"><div><strong>Acquired Podcast</strong></div><div>Deep company history + competitive moats. 3-5hr deep dives.</div><div class="lag-mid">Thesis building</div></div>
  <div class="source-row"><div><strong>All-In Podcast</strong></div><div>Tech + macro + geopolitics synthesis. Chamath, Sacks, Friedberg, Palihapitiya.</div><div class="lag-mid">Macro signals</div></div>
  <div class="source-row"><div><strong>Andrej Karpathy</strong></div><div>AI/LLM technical depth. Ex-Tesla AI. Knows physical AI from the inside.</div><div class="lag-mid">Robotics/AI depth</div></div>
  <div class="source-row"><div><strong>Patrick Boyle</strong></div><div>Finance + markets. Institutional perspective. Pushback on retail hype.</div><div class="lag-mid">Sanity check</div></div>
</div>
<div class="section-title">📅 Conference Calendar - Price Moves Happen Here</div>
<div class="conf-wrap">
  <div class="conf-row hdr"><div>Event</div><div>Timing</div><div>Tickers to Watch</div></div>
  <div class="conf-row"><div><strong>NVIDIA GTC</strong></div><div>Annual - March</div><div>NVDA, AMD, ASML, BOTZ, robotics plays</div></div>
  <div class="conf-row"><div><strong>CES Las Vegas</strong></div><div>Annual - January</div><div>Consumer tech, EV, IoT, smart devices</div></div>
  <div class="conf-row"><div><strong>NeurIPS (AI Research)</strong></div><div>Annual - December</div><div>AI stocks, NVDA, GOOGL, MSFT, AMZN</div></div>
  <div class="conf-row"><div><strong>Apple WWDC</strong></div><div>Annual - June</div><div>AAPL + app ecosystem</div></div>
  <div class="conf-row"><div><strong>NATO Summit</strong></div><div>Annual - July</div><div>RTX, NOC, ITA, LMT, KTOS, BAE</div></div>
  <div class="conf-row"><div><strong>World Nuclear Symposium</strong></div><div>Annual - Sept</div><div>CCJ, NUCL, OKLO, SMR plays</div></div>
</div>
"""

    RULES_TAB = """
<div class="rule-box" style="background:#0f172a;border:1px solid #ef4444;">
  <h3 style="color:#f87171;">🔴 Morning Protocol - Run in This Order Every Session</h3>
  <div class="rule-item"><span class="rule-num">0.</span>Check market hours FIRST. Past 1:00 PM MST = market CLOSED. Planning mode only - no orders.</div>
  <div class="rule-item"><span class="rule-num">1.</span>News sweep BEFORE any charts - ticker news + macro narratives. NEWS FIRST.</div>
  <div class="rule-item"><span class="rule-num">2.</span>Dot connector - does any news link to Iran war / Europe rearmament / rare earth / AI buildout / nuclear? Map it to positions.</div>
  <div class="rule-item"><span class="rule-num">3.</span>Run live yfinance snapshot on all open positions. Flag any GTC within $0.50 of filling.</div>
  <div class="rule-item"><span class="rule-num">4.</span>SPY/QQQ RSI - flag if &gt;75 (overbought) or &lt;35 (oversold). Affects sizing.</div>
  <div class="rule-item"><span class="rule-num">5.</span>Trump signal check - any overnight Truth Social post? Maps to trade table in Trump tab.</div>
  <div class="rule-item"><span class="rule-num">6.</span>Output: fills to act on, stops to set, alerts, any new entry candidates.</div>
</div>
<div class="section-title">📦 5 Position Types</div>
<div class="type-grid">
  <div class="type-card"><span class="type-badge t-swing">S - SWING</span><div class="type-name">Swing Trade (ROTH only)</div><div class="type-detail">RSI 35-50 · Score 60-79 · $750-1K<br>Stop: −8% hard GTC immediately on fill<br>Exit: +5%→BE · +10%→sell 50% · +20%→sell all<br>Day 30 auto-exit, no exceptions<br>Averaging down: NO</div></div>
  <div class="type-card"><span class="type-badge t-long">L - LONG HOLD</span><div class="type-name">Long Hold (ROTH or TOD)</div><div class="type-detail">RSI &lt;35 · Score 80+ · $1K-2K<br>Stop: −15% disaster only (fraud/collapse)<br>−8% from entry = ADD ZONE (not exit)<br>Exit: +15%→25% · +30%→50% · No time limit<br>Averaging down: YES, max 2 adds</div></div>
  <div class="type-card"><span class="type-badge t-income">I - INCOME</span><div class="type-name">Income / MLP (ROTH only)</div><div class="type-detail">High yield (4%+) · EPD, ET, KMI<br>Stop: NONE. Exit ONLY on distribution cut<br>Do NOT exit on oil price drops - revenue is volume-based<br>Hold indefinitely. Reinvest distributions.</div></div>
  <div class="type-card"><span class="type-badge t-life">LIFETIME</span><div class="type-name">Forever Hold (TOD only)</div><div class="type-detail">Irreplaceable moat · 5-15 year hold<br>ASML, AMD, TSM, NVDA, META, AAPL, MSFT, GOOGL, AMZN, NFLX<br>Stop: NONE. Ever.<br>Exit: business collapse only (fraud, moat broken, tech obsolete)</div></div>
  <div class="type-card" style="grid-column:1/-1;"><span class="type-badge t-spec">SPEC - SPECULATIVE</span><div class="type-name">Lottery Bet (TOD only)</div><div class="type-detail">High-risk future bet · $200-500 MAX · BBAI, ACHR, IONQ, KTOS (post-earnings), PLTR<br>Stop: NONE. Accept binary outcome. Exit: defined floor (e.g. BBAI below $2.50) or thesis gone.<br>Never let a Spec position grow beyond 5% of TOD without trimming.</div></div>
</div>
<div class="rule-box">
  <h3>🛑 Stop Order Rules (Never Break These)</h3>
  <div class="rule-item"><span class="rule-num">1.</span>ALWAYS GTC Stop Market. Never Stop Limit. Never Day orders (Day orders expire overnight silently).</div>
  <div class="rule-item"><span class="rule-num">2.</span>Type S: stop −8% from entry. Type L: stop −15% (disaster only). Set BEFORE entering, not after.</div>
  <div class="rule-item"><span class="rule-num">3.</span>Swing exits are driven by thesis, NOT calendar. A trade at day 20 with intact thesis is a working trade.</div>
  <div class="rule-item"><span class="rule-num">4.</span>Never sell without simultaneously placing the re-entry limit order. The Meta mistake.</div>
  <div class="rule-item"><span class="rule-num">5.</span>Type I (Income) and Lifetime: NEVER set a GTC stop. Exit only on thesis collapse.</div>
</div>
<div class="rule-box">
  <h3>📐 Entry Rules</h3>
  <div class="rule-item"><span class="rule-num">1.</span>Stocks: 180-pt algorithm. ≥70 = candidate. ≥110 = strong. ≥140 = high conviction. Earnings &lt;15 days = AUTO-DISQUALIFY.</div>
  <div class="rule-item"><span class="rule-num">2.</span>ETFs: RSI + BB% + MACD only. ≥60 pts = buy. No earnings/FCF/D/E concerns.</div>
  <div class="rule-item"><span class="rule-num">3.</span>Never market order on entry. GTC limit always.</div>
  <div class="rule-item"><span class="rule-num">4.</span>Split entry: 30-50% at market + GTC rest at lower price for large positions.</div>
</div>
<div class="rule-box">
  <h3>💰 Position Sizing</h3>
  <div class="rule-item"><span class="rule-num">•</span>Beta 1.0-1.3 = $1,000 · Beta 1.3-1.6 = $750 · Beta &gt;1.6 = $500</div>
  <div class="rule-item"><span class="rule-num">•</span>VIX &gt;25 = −25% all positions · VIX &gt;35 = −50% all positions</div>
  <div class="rule-item"><span class="rule-num">•</span>2nd same-sector stock = max $500 · Short ratio &gt;5 = −25%</div>
  <div class="rule-item"><span class="rule-num">⚠️</span>NEVER use stale cash figures from this tracker. Always check Fidelity for actual cash before sizing.</div>
</div>
<div class="rule-box">
  <h3>🧠 Investor Principles</h3>
  <div class="rule-item"><span class="rule-num">Buffett</span>"Be fearful when others are greedy, greedy when others are fearful."</div>
  <div class="rule-item"><span class="rule-num">Munger</span>"The big money is in the waiting." But: "By the time you're comfortable, the price is gone."</div>
  <div class="rule-item"><span class="rule-num">Klarman</span>Define margin of safety BEFORE buying. 15-20% below fair value = acceptable entry.</div>
  <div class="rule-item"><span class="rule-num">Druckenmiller</span>"Concentration is the key to great performance." TOD tech concentration = intentional.</div>
  <div class="rule-item"><span class="rule-num">Lynch</span>Know what you own and why. Write 2 sentences: why you own it, what makes you sell.</div>
</div>
<div class="rule-box">
  <h3>📚 Hard-Learned Lessons</h3>
  <div class="rule-item"><span class="rule-num">Meta</span>Sold expecting drop. Market went up. Never sell without a simultaneous re-entry limit order.</div>
  <div class="rule-item"><span class="rule-num">Day Order</span>BJ stop as Day order. Expired overnight. No stop for a day. ALWAYS GTC. Never Day.</div>
  <div class="rule-item"><span class="rule-num">Apr 2026</span>Panic sold META, MSFT, SOXX on tariff/Iran fear. Cost ~$2,500. Businesses weren't damaged. HOLD.</div>
  <div class="rule-item"><span class="rule-num">Timing</span>Missing 10 best days out of 5,000 cuts returns in half. 7 of 10 best days = within 2 weeks of 10 worst.</div>
</div>
<div class="rule-box" style="background:#0a1f0a;border:1px solid #10b981;margin-top:10px;">
  <h3 style="color:#4ade80;">🎯 Combined Portfolio $50K Target (ROTH + TOD)</h3>
  <div class="rule-item"><span class="rule-num">Monthly</span>$500 ROTH + $400 TOD = $900/mo = $10,800/yr total investing.</div>
  <div class="rule-item"><span class="rule-num">Target</span>$50K combined → 2027 event. At 15% returns + $900/mo. You're close.</div>
  <div class="rule-item"><span class="rule-num">Next</span>$100K combined. At 15% returns + $900/mo → hits ~$80K by end 2028. $100K by mid-2030.</div>
  <div class="rule-item"><span class="rule-num">Lump sum</span>Any bonus/tax refund → ROTH first (IRS limit $7,500/yr), then TOD. ROTH compounding is tax-free forever.</div>
</div>
"""

    # ── Assemble full HTML ─────────────────────────────────────────────────
    roth_gl_pct = (roth_pos_gl / (roth_pos_total - roth_pos_gl) * 100) if (roth_pos_total - roth_pos_gl) else 0
    gl_color_r = "#4ade80" if roth_pos_gl >= 0 else "#f87171"
    gl_color_t = "#4ade80" if tod_pos_gl >= 0 else "#f87171"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tan's Portfolio Tracker - {today}</title>
<style>{CSS}</style></head><body>

<div class="alert-bar">{alert_pills_html}</div>

<div class="header">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
    <div><h1>📊 Tan's Portfolio Tracker</h1>
    <div class="header-meta">Fidelity · Roth IRA *{roth_id[-4:]} + Individual TOD {tod_id} · Updated {today} · python morning_run.py</div></div>
    <div style="text-align:right;"><div style="font-size:10px;color:#94a3b8;">Cash balances → always verify in Fidelity</div>
    <div style="font-size:11px;color:{market_badge_color};font-weight:700;margin-top:4px;">{'● MARKET OPEN' if market_open else '● MARKET CLOSED'} · {market_status_str}</div></div>
  </div>
  <div class="header-stats">
    <div><div class="stat-label">ROTH IRA Total</div><div class="stat-value">${roth_total:,.0f}</div><div class="stat-sub {'red' if roth_pos_gl < 0 else ''}">Positions ${roth_pos_total:,.0f} ({sign(roth_gl_pct)}{roth_gl_pct:.1f}%) · ${roth_cash:,.0f} cash</div></div>
    <div><div class="stat-label">TOD Total</div><div class="stat-value">${tod_total:,.0f}</div><div class="stat-sub">Positions ${tod_pos_total:,.0f} · ${tod_cash:,.0f} cash</div></div>
    <div><div class="stat-label">Grand Total</div><div class="stat-value">${grand_total:,.0f}</div><div class="stat-sub">ROTH + TOD combined</div></div>
    <div><div class="stat-label">Live as of</div><div class="stat-value" style="font-size:11px;">{today}</div><div class="stat-sub" style="color:#10b981;">yfinance</div></div>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('today',this)">📌 Today</div>
  <div class="tab" onclick="switchTab('roth',this)">🔵 Roth IRA</div>
  <div class="tab" onclick="switchTab('tod',this)">🟢 TOD</div>
  <div class="tab" onclick="switchTab('perf',this)">📊 Performance</div>
  <div class="tab" onclick="switchTab('etfs',this)">📈 ETFs</div>
  <div class="tab" onclick="switchTab('geo',this)">🌍 Geo</div>
  <div class="tab" onclick="switchTab('themes',this)">🚀 Themes</div>
  <div class="tab" onclick="switchTab('sectors',this)">🗂 Sectors</div>
  <div class="tab" onclick="switchTab('calendar',this)">📅 Calendar</div>
  <div class="tab" onclick="switchTab('trump',this)">⚡ Trump</div>
  <div class="tab" onclick="switchTab('research',this)">🔬 Research</div>
  <div class="tab" onclick="switchTab('rules',this)">📋 Rules</div>
</div>

<!-- TODAY -->
<div id="tab-today" class="content active">
  <div class="section-title">📋 Today's Trade Recommendations</div>
  <div class="card" style="padding:0;overflow:auto;">{action_items_html}</div>

  <div class="section-title" style="margin-top:12px;">🔴 Alerts &amp; GTC Proximity</div>
  <div class="orders-grid">{today_cards}</div>

  <div class="section-title" style="margin-top:12px;">🧠 Market Conditions + Position Health</div>
  <div class="card" style="padding:12px 14px;">{daily_read_html}</div>

  <div class="section-title">🌍 Macro Narrative News</div>
  <div class="card" style="padding:12px 14px;">{macro_status_html or '<div style="color:#94a3b8;font-size:11px;">Set NEWSAPI_KEY in .env to enable macro news feed.</div>'}</div>

  <div class="section-title">🟡 Conditional (Come Back Daily - Pending GTC Triggers)</div>
  <div class="card"><table>
    <tr><th>Trigger</th><th>Action</th><th>Account</th></tr>
    {cond_rows}
  </table></div>
</div>

<!-- ROTH IRA -->
<div id="tab-roth" class="content">
  <div class="section-title">🔵 Roth IRA *{roth_id[-4:]} - Live Positions · {today}</div>
  <div class="card"><table>
    <tr><th>Symbol</th><th>Type</th><th>Avg Cost</th><th>Now</th><th>Sh</th><th>Value</th><th>G/L $</th><th>G/L %</th><th>Stop GTC</th><th>RSI</th></tr>
    {roth_rows}
  </table></div>

  <div class="section-title">⏳ Pending GTC Orders (ROTH) - IRA contribution limit $7,500/yr</div>
  <div class="orders-grid">{roth_pending}</div>

  <div class="section-title">⚠️ Thesis Breakers - Check Daily</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
    <div class="card" style="padding:10px 12px;"><div style="font-weight:700;margin-bottom:6px;">CRM 🤖</div><div style="font-size:11px;color:#64748b;line-height:1.6;">Revenue growth turns negative · Microsoft bundles CRM into M365 free · Benioff exits</div></div>
    <div class="card" style="padding:10px 12px;"><div style="font-weight:700;margin-bottom:6px;">MDT 🏥</div><div style="font-size:11px;color:#64748b;line-height:1.6;">Guidance cut · Dividend cut · Major device recall</div></div>
    <div class="card" style="padding:10px 12px;"><div style="font-weight:700;margin-bottom:6px;">EPD ⚡</div><div style="font-size:11px;color:#64748b;line-height:1.6;">Distribution cut · Pipeline volume collapse · Regulatory shutdown. NOT oil price drops - revenue is volume-based.</div></div>
    <div class="card" style="padding:10px 12px;"><div style="font-weight:700;margin-bottom:6px;">MP 🪨</div><div style="font-size:11px;color:#64748b;line-height:1.6;">China lifts RE ban (unlikely) · US finds major alternative supplier · Mine-to-magnet program cancelled</div></div>
    <div class="card" style="padding:10px 12px;"><div style="font-weight:700;margin-bottom:6px;">RTX ✈️</div><div style="font-size:11px;color:#64748b;line-height:1.6;">Defense budget cut &gt;20% · Major contract cancellation. Iran peace deal = short-term dip only, NOT thesis breaker.</div></div>
    <div class="card" style="padding:10px 12px;"><div style="font-weight:700;margin-bottom:6px;">NOC ✈️</div><div style="font-size:11px;color:#64748b;line-height:1.6;">Defense budget cut &gt;20% · Major contract loss · Exit when thesis breaks, not on a date</div></div>
    <div class="card" style="padding:10px 12px;"><div style="font-weight:700;margin-bottom:6px;">GLD 🥇</div><div style="font-size:11px;color:#64748b;line-height:1.6;">Fed aggressively cuts AND dollar surges AND central banks dump reserves simultaneously</div></div>
    <div class="card" style="padding:10px 12px;"><div style="font-weight:700;margin-bottom:6px;">BJ 🛒</div><div style="font-size:11px;color:#64748b;line-height:1.6;">Consumer spending collapses below membership renewal - recession so bad people cancel warehouse memberships</div></div>
  </div>
</div>

<!-- TOD -->
<div id="tab-tod" class="content">
  <div class="section-title">🟢 TOD {tod_id} - Live Positions · {today}</div>
  <div class="card"><table>
    <tr><th>Symbol</th><th>Type</th><th>Avg Cost</th><th>Now</th><th>Sh</th><th>Value</th><th>G/L $</th><th>G/L %</th><th>Thesis</th></tr>
    {tod_rows}
  </table></div>

  <div class="section-title">⏳ Pending GTC Orders (TOD)</div>
  <div class="orders-grid">{tod_pending}</div>

  <div class="cash-bar">
    <div style="display:flex;justify-content:space-between;"><span style="font-weight:700;">TOD Cash Available</span><span style="font-weight:700;color:#10b981;">${tod_cash:,.2f} available</span></div>
    <div style="font-size:10px;color:#64748b;margin-top:4px;">Priority: 1. ITA ETF (defense, ~$1,080) → 2. V or BRK-B (~$300 financials) → 3. CCJ nuclear (~$230)</div>
  </div>

  <div class="section-title">🎯 TOD Next Adds (Priority Order)</div>
  <div class="card"><table>
    <tr><th>Symbol</th><th>Type</th><th>Entry Target</th><th>Size</th><th>Trigger</th><th>Why</th></tr>
    <tr><td><span class="sym">ITA</span></td><td><span class="t-etf">ETF</span></td><td>$210-216, 5sh</td><td>~$1,080</td><td>Wait MACD turn (RSI deeply oversold ✅)</td><td>Defense ETF. Active Iran war + Europe rearmament. Deeply oversold in a defense bull market.</td></tr>
    <tr><td><span class="sym">V</span></td><td><span class="t-life">LIFE</span></td><td>$295 or below, 1sh</td><td>~$295</td><td>Earnings dip or pullback</td><td>Fills financials gap (currently $0 in financials)</td></tr>
    <tr><td><span class="sym">KTOS</span></td><td><span class="t-spec">SPEC</span></td><td>Beat:$62-65 / Miss:$52-55</td><td>$300-500</td><td>Post May 6 earnings</td><td>Drones + hypersonics. RSI oversold. Active Iran war = defense premium.</td></tr>
    <tr><td><span class="sym">CCJ</span></td><td><span class="t-life">LIFE</span></td><td>$110-115, 1-2sh</td><td>~$230</td><td>Pullback or nuclear news</td><td>Uranium king. Every new nuclear PPA = CCJ goes up.</td></tr>
  </table></div>
</div>

<!-- PERFORMANCE -->
<div id="tab-perf" class="content">
  <div class="section-title">📊 Portfolio Equity Curve</div>
  <div class="card" style="padding:16px;">
    <canvas id="equityChart" style="max-height:300px;"></canvas>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:10px;">
    {perf_summary_cards}
  </div>

  <div class="section-title" style="margin-top:14px;">📋 Closed Trades - Realized P&L</div>
  <div class="card" style="padding:0;overflow:auto;">
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:#f8fafc;">
        <th style="text-align:left;font-size:10px;color:#94a3b8;padding:6px 8px;">Date</th>
        <th style="text-align:left;font-size:10px;color:#94a3b8;padding:6px;">Ticker</th>
        <th style="text-align:left;font-size:10px;color:#94a3b8;padding:6px;">Acct</th>
        <th style="text-align:right;font-size:10px;color:#94a3b8;padding:6px;">Shares</th>
        <th style="text-align:right;font-size:10px;color:#94a3b8;padding:6px;">Avg Cost</th>
        <th style="text-align:right;font-size:10px;color:#94a3b8;padding:6px;">Sell Price</th>
        <th style="text-align:right;font-size:10px;color:#94a3b8;padding:6px;">P&amp;L $</th>
        <th style="text-align:right;font-size:10px;color:#94a3b8;padding:6px;">P&amp;L %</th>
        <th style="text-align:right;font-size:10px;color:#94a3b8;padding:6px;">Hold Days</th>
      </tr>
      {trades_rows}
    </table>
  </div>
</div>

<!-- ETFs -->
<div id="tab-etfs" class="content">
  <div class="section-title">📈 ETF Watchlist - Live Technicals</div>
  <div class="geo-key" style="margin-bottom:12px;">For ETFs: skip FCF/earnings/D/E checks. Use RSI + BB% + MACD only. Score ≥60 = buy. ITA = only current buy signal - wait for MACD turn.</div>
  <div class="etf-wrap">
    <div class="etf-row hdr"><div>ETF</div><div>Theme</div><div>RSI</div><div>BB%</div><div>MACD↑</div><div>Signal</div><div>Entry Target</div></div>
    {etf_rows}
  </div>
  <div class="section-title">🎯 ETF Scoring (Simplified)</div>
  <div class="card"><table>
    <tr><th>Factor</th><th>Points</th></tr>
    <tr><td>RSI &lt; 30</td><td>30 pts</td></tr><tr><td>RSI &lt; 40</td><td>15 pts</td></tr>
    <tr><td>BB% &lt; 20</td><td>25 pts</td></tr><tr><td>BB% &lt; 40</td><td>10 pts</td></tr>
    <tr><td>MACD histogram improving</td><td>20 pts</td></tr>
    <tr><td>Macro tailwind confirmed</td><td>15 pts</td></tr>
    <tr><td>VIX &gt; 20 (fear = opportunity)</td><td>10 pts</td></tr>
  </table></div>
  <div class="geo-key">≥60 = buy · ≥80 = aggressive buy. No earnings/FCF/D/E checks for ETFs.</div>
</div>

<!-- GEOPOLITICS -->
<div id="tab-geo" class="content">{GEO_TAB}</div>

<!-- THEMES -->
<div id="tab-themes" class="content">{THEMES_TAB}</div>

<!-- SECTORS -->
<div id="tab-sectors" class="content">{SECTORS_TAB}</div>

<!-- CALENDAR -->
<div id="tab-calendar" class="content">
  <div class="section-title">💰 Dividend Calendar - Upcoming Ex-Dates &amp; Payouts</div>
  <div class="card"><table>
    <tr><th>Ticker</th><th>Ex-Date</th><th>Pay Date</th><th>Yield</th><th>Annual/sh</th><th>Projected Income</th></tr>
    {div_event_rows}
  </table></div>

  <div class="section-title">📅 Earnings Calendar - Next 45 Days</div>
  <div class="card"><table>
    <tr><th>Ticker</th><th>Days Until</th><th>Alert</th></tr>
    {earn_event_rows}
  </table></div>

  <div class="section-title">📌 Key Events (Manual - Update as Needed)</div>
  <div class="event-list">
    <div class="event"><div class="event-day done">APR 28</div><div><div class="event-title">EPD Q1 BEAT ✅</div><div class="event-sub"><span class="tag tag-done">EPD BEAT</span> Rev $14.39B. Iran war = US LPG export surge. Iran war thesis confirmed by earnings.</div></div></div>
    <div class="event"><div class="event-day warn">MAY 5</div><div><div class="event-title">BBAI Earnings (~May 5)</div><div class="event-sub"><span class="tag tag-watch">WATCH</span> 50sh @$4.95. Lottery ticket - hold unless thesis collapses or drops below $2.50.</div></div></div>
    <div class="event"><div class="event-day warn">MAY 6</div><div><div class="event-title">KTOS Earnings</div><div class="event-sub"><span class="tag tag-watch">WATCH</span> RSI oversold - deeply oversold. Beat: buy $62-65, 5sh, TOD. Miss: buy $52-55, 8sh, TOD aggressively.</div></div></div>
    <div class="event"><div class="event-day">JUN 3</div><div><div class="event-title">MDT Earnings</div><div class="event-sub"><span class="tag tag-hold">HOLD</span> ROTH long. Holding thesis. Analyst target $109.</div></div></div>
    <div class="event"><div class="event-day">ANN</div><div><div class="event-title">NVIDIA GTC (March annually)</div><div class="event-sub">🚀 Jensen's keynote = 2-year market roadmap. Act immediately on robotics/AI plays.</div></div></div>
  </div>
</div>

<!-- TRUMP -->
<div id="tab-trump" class="content">{TRUMP_TAB}</div>

<!-- RESEARCH -->
<div id="tab-research" class="content">{RESEARCH_TAB}</div>

<!-- RULES -->
<div id="tab-rules" class="content">
  {RULES_TAB}
  <div class="updated-note">Updated {today} · python morning_run.py · Always check Fidelity for live balances</div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
function switchTab(name, el) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'perf' && !window._chartBuilt) {{
    buildEquityChart();
    window._chartBuilt = true;
  }}
}}

function buildEquityChart() {{
  const ctx = document.getElementById('equityChart');
  if (!ctx) return;
  const dates = {chart_dates_json};
  const total = {chart_total_json};
  const roth  = {chart_roth_json};
  const tod   = {chart_tod_json};
  if (dates.length < 2) {{
    const msg = document.createElement('div');
    msg.style.cssText = 'padding:40px;text-align:center;color:#94a3b8;font-size:13px;';
    msg.textContent = 'Equity curve builds after a few morning runs - come back tomorrow.';
    ctx.parentElement.replaceChild(msg, ctx);
    return;
  }}
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: dates,
      datasets: [
        {{ label: 'Total', data: total, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.08)', tension: 0.3, pointRadius: 3, borderWidth: 2 }},
        {{ label: 'ROTH',  data: roth,  borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.05)', tension: 0.3, pointRadius: 2, borderWidth: 1.5 }},
        {{ label: 'TOD',   data: tod,   borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.05)', tension: 0.3, pointRadius: 2, borderWidth: 1.5 }},
      ]
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ position: 'top', labels: {{ font: {{ size: 11 }} }} }},
        tooltip: {{ callbacks: {{ label: c => ' $' + c.raw.toLocaleString() }} }}
      }},
      scales: {{
        y: {{ ticks: {{ callback: v => '$' + v.toLocaleString(), font: {{ size: 10 }} }}, grid: {{ color: '#f1f5f9' }} }},
        x: {{ ticks: {{ font: {{ size: 10 }}, maxTicksLimit: 12 }}, grid: {{ display: false }} }}
      }}
    }}
  }});
}}
</script>
</body></html>"""


