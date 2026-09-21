#!/usr/bin/env python3
"""
refactor_validate.py - Functional validation for morning_run.py refactor.

Text-diff fails on order non-determinism. Instead validate deterministic
structures: daily_brief.json keys, counts, types. Each refactor step must
produce identical structure.

Usage:
    # Before refactor:
    python3 morning_run.py
    python3 refactor_validate.py --save baseline.json

    # After each refactor step:
    python3 morning_run.py
    python3 refactor_validate.py --check baseline.json

Exits 0 if structure matches baseline, 1 if any deviation.
"""
import json, sys
from pathlib import Path

BRIEF = Path(__file__).resolve().parents[1] / "daily_brief.json"


def fingerprint(brief: dict) -> dict:
    """Extract deterministic structural fingerprint, exclude live-data fields."""
    out = {
        "top_keys":        sorted(brief.keys()),
        "earnings_alerts": len(brief.get("earnings_alerts", [])),
        "probable_fills":  len(brief.get("probable_fills", [])),
        "stop_alerts":     len(brief.get("stop_alerts", [])),
        "top_actions":     len(brief.get("top_actions", [])),
        "watchlist":       len(brief.get("watchlist", [])),
        "hard_rules":      len(brief.get("hard_rules", [])),
        "positions_count": len(brief.get("positions", {})),
        "positions_keys":  sorted(brief.get("positions", {}).keys()),
        "insider_keys":    sorted(brief.get("insider_signals", {}).keys()),
        "options_keys":    sorted(brief.get("options_flow", {}).keys()),
        "portfolio_keys":  sorted(brief.get("portfolio", {}).keys()),
        "market_keys":     sorted(brief.get("market", {}).keys()),
    }
    # Per-position structural keys (not values - prices change)
    pos_struct = {}
    for tkr, pos in brief.get("positions", {}).items():
        if isinstance(pos, dict):
            pos_struct[tkr] = sorted(pos.keys())
    out["position_struct"] = pos_struct
    return out


def diff(a: dict, b: dict, path: str = "") -> list[str]:
    issues = []
    keys = set(a.keys()) | set(b.keys())
    for k in sorted(keys):
        p = f"{path}.{k}" if path else k
        if k not in a:
            issues.append(f"+ {p} (added)")
        elif k not in b:
            issues.append(f"- {p} (removed)")
        elif isinstance(a[k], dict) and isinstance(b[k], dict):
            issues.extend(diff(a[k], b[k], p))
        elif a[k] != b[k]:
            issues.append(f"~ {p}: {a[k]!r} → {b[k]!r}")
    return issues


def main():
    args = sys.argv[1:]
    if not BRIEF.exists():
        print(f"ERROR: {BRIEF} missing. Run morning_run.py first.")
        sys.exit(1)

    brief = json.load(open(BRIEF, encoding="utf-8"))
    fp = fingerprint(brief)

    if "--save" in args:
        out = args[args.index("--save") + 1]
        json.dump(fp, open(out, "w", encoding="utf-8"), indent=2, sort_keys=True)
        print(f"Baseline saved → {out}")
        print(f"  positions={fp['positions_count']}  actions={fp['top_actions']}  "
              f"watchlist={fp['watchlist']}  alerts={fp['stop_alerts']+fp['probable_fills']+fp['earnings_alerts']}")
        return

    if "--check" in args:
        baseline_path = args[args.index("--check") + 1]
        baseline = json.load(open(baseline_path, encoding="utf-8"))
        issues = diff(baseline, fp)
        if issues:
            print(f"REGRESSION ({len(issues)} differences vs {baseline_path}):")
            for issue in issues:
                print(f"  {issue}")
            sys.exit(1)
        print(f"✓ Structural match against {baseline_path}")
        print(f"  positions={fp['positions_count']}  actions={fp['top_actions']}  "
              f"watchlist={fp['watchlist']}")
        return

    # Default: print fingerprint
    print(json.dumps(fp, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
