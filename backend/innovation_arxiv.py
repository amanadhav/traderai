"""
innovation_arxiv.py - arXiv research-paper signal extractor (innovation_score Step 1/3).

Searches arxiv.org for papers mentioning a company OR with authors at company
affiliation, in last N months. Sparse-by-design: most tickers return zero
matches (correct - only frontier-tech tickers have arXiv presence).

Public API:
    fetch_arxiv_signal(ticker, months=12, force_refresh=False) -> dict
    get_arxiv_signals(tickers, force_refresh=False, verbose=False) -> dict

Returns per ticker:
    {
        "has_data":     bool,
        "paper_count":  int,
        "categories":   list[str],   # cs.AI, cs.LG, quant-ph, etc.
        "top_papers":   list[{title, authors, published, abstract_snippet, url}],
        "fetched_at":   str (ISO),
        "note":         str,
    }

Caching: 7d TTL at data/innovation_cache/{ticker}_arxiv.json (gitignored).
Rate limit: 3-second polite delay between API calls (arXiv recommendation).

Mapping ticker → search terms requires hand-curation. Some tickers map to
multiple terms (e.g. GOOGL → "Google", "DeepMind", "Google Research").
"""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import requests


BASE = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE / "data" / "innovation_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_DAYS = 7
HTTP_TIMEOUT = 15
ARXIV_DELAY_SEC = 3.0     # polite - arXiv recommendation
ARXIV_API = "http://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


# ── Ticker → arXiv search terms ─────────────────────────────────────────────
# Hand-curated. Tickers not in this map return has_data=False (correct -
# arXiv coverage is sparse, no need to fake a signal for retail/midstream).
ARXIV_SEARCH_TERMS: dict[str, list[str]] = {
    # AI/ML hyperscalers
    "GOOGL": ["Google Research", "DeepMind"],
    "GOOG":  ["Google Research", "DeepMind"],
    "MSFT":  ["Microsoft Research"],
    "META":  ["FAIR Meta", "Facebook AI Research"],
    "AMZN":  ["Amazon Science", "AWS AI"],
    "AAPL":  ["Apple Machine Learning"],
    # Semiconductors
    "NVDA":  ["NVIDIA Research"],
    "AMD":   ["AMD Research"],
    "INTC":  ["Intel Labs"],
    "ASML":  ["ASML"],
    "TSM":   ["TSMC"],
    "QCOM":  ["Qualcomm AI Research"],
    "ARM":   ["Arm"],
    # Quantum
    "IBM":   ["IBM Quantum", "IBM Research"],
    "IONQ":  ["IonQ"],
    "RGTI":  ["Rigetti"],
    "QBTS":  ["D-Wave"],
    # Biotech / pharma research-active
    "REGN":  ["Regeneron"],
    "MRNA":  ["Moderna"],
    "BNTX":  ["BioNTech"],
    "NVO":   ["Novo Nordisk"],
    "LLY":   ["Eli Lilly"],
    "VRTX":  ["Vertex Pharmaceuticals"],
    "AMGN":  ["Amgen"],
    "GILD":  ["Gilead Sciences"],
    "PFE":   ["Pfizer"],
    "MRK":   ["Merck"],
    # Robotics / aerospace
    "TSLA":  ["Tesla AI"],
    "RKLB":  ["Rocket Lab"],
    "ISRG":  ["Intuitive Surgical"],
    # AI infra-adjacent
    "PLTR":  ["Palantir"],
    "CRWV":  ["CoreWeave"],
}


# ── Cache helpers ───────────────────────────────────────────────────────────

def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}_arxiv.json"


def _is_fresh(path: Path, ttl_days: float = CACHE_TTL_DAYS) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    return age < ttl_days * 86400


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if _is_fresh(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(ticker: str, data: dict) -> None:
    _cache_path(ticker).write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── arXiv fetcher (Atom feed) ───────────────────────────────────────────────

def _arxiv_search(term: str, months: int = 12, max_results: int = 20) -> list[dict]:
    """Search arXiv for `term` in last N months. Returns list of paper dicts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * months)
    cutoff_str = cutoff.strftime("%Y%m%d%H%M%S")

    # arXiv query: search title/abstract/affiliation, sort by date desc
    query = f'(ti:"{term}" OR abs:"{term}" OR au:"{term}")'
    params = {
        "search_query": query,
        "sortBy":       "submittedDate",
        "sortOrder":    "descending",
        "max_results":  max_results,
    }

    try:
        time.sleep(ARXIV_DELAY_SEC)
        resp = requests.get(ARXIV_API, params=params, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.text)
    except Exception:
        return []

    papers = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title_el = entry.find("atom:title", ATOM_NS)
        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
        if not title:
            continue
        published_el = entry.find("atom:published", ATOM_NS)
        published = (published_el.text or "").strip()[:10] if published_el is not None else ""
        if published and published < cutoff.strftime("%Y-%m-%d"):
            continue
        abstract_el = entry.find("atom:summary", ATOM_NS)
        abstract = (abstract_el.text or "").strip().replace("\n", " ") if abstract_el is not None else ""
        url_el = entry.find("atom:id", ATOM_NS)
        url = (url_el.text or "").strip() if url_el is not None else ""
        # Authors
        authors = []
        for a in entry.findall("atom:author", ATOM_NS):
            name = a.find("atom:name", ATOM_NS)
            if name is not None and name.text:
                authors.append(name.text.strip())
        # Categories (primary classification)
        cats = []
        for c in entry.findall("atom:category", ATOM_NS):
            term_attr = c.attrib.get("term", "")
            if term_attr and term_attr not in cats:
                cats.append(term_attr)

        papers.append({
            "title":     title[:200],
            "authors":   authors[:4],
            "published": published,
            "abstract":  abstract[:300],
            "categories": cats[:3],
            "url":       url,
        })
    return papers


def _categorize_papers(papers: list[dict]) -> list[str]:
    """Aggregate primary arXiv categories across all papers."""
    cats: dict[str, int] = {}
    for p in papers:
        for c in p.get("categories", []):
            cats[c] = cats.get(c, 0) + 1
    return [c for c, _ in sorted(cats.items(), key=lambda kv: kv[1], reverse=True)[:5]]


# ── Public API ──────────────────────────────────────────────────────────────

def fetch_arxiv_signal(ticker: str, months: int = 12,
                       force_refresh: bool = False) -> dict:
    """Fetch arXiv signal for one ticker. Caches 7d. ~3sec API call cost."""
    ticker = ticker.upper()
    if ticker not in ARXIV_SEARCH_TERMS:
        # Sparse-by-design - many tickers have no arXiv presence
        return {
            "has_data":    False,
            "paper_count": 0,
            "categories":  [],
            "top_papers":  [],
            "fetched_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note":        f"{ticker} not in ARXIV_SEARCH_TERMS - no research signal",
        }

    if not force_refresh:
        cached = _load_cache(ticker)
        if cached:
            return cached

    all_papers: list[dict] = []
    for term in ARXIV_SEARCH_TERMS[ticker]:
        papers = _arxiv_search(term, months=months)
        all_papers.extend(papers)

    # Dedupe by URL
    seen, unique = set(), []
    for p in all_papers:
        url = p.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        unique.append(p)

    # Sort by date desc
    unique.sort(key=lambda p: p.get("published", ""), reverse=True)

    result = {
        "has_data":    True,
        "paper_count": len(unique),
        "categories":  _categorize_papers(unique),
        "top_papers":  [
            {"title": p["title"], "authors": p["authors"][:2],
             "published": p["published"], "url": p["url"],
             "abstract_snippet": p["abstract"][:160]}
            for p in unique[:5]
        ],
        "fetched_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note":        f"matched {len(ARXIV_SEARCH_TERMS[ticker])} search terms",
    }
    _save_cache(ticker, result)
    return result


def get_arxiv_signals(tickers: list[str], force_refresh: bool = False,
                      verbose: bool = False) -> dict[str, dict]:
    results = {}
    for t in tickers:
        if verbose:
            print(f"  arXiv: {t}...", end=" ", flush=True)
        results[t.upper()] = fetch_arxiv_signal(t, force_refresh=force_refresh)
        if verbose:
            r = results[t.upper()]
            print(f"{r['paper_count']} papers" if r["has_data"] else "skipped (not in map)")
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python innovation_arxiv.py TICKER [...] [--refresh]")
        sys.exit(1)
    refresh = "--refresh" in sys.argv
    tickers = [a for a in sys.argv[1:] if not a.startswith("--")]
    sigs = get_arxiv_signals(tickers, force_refresh=refresh, verbose=True)
    print()
    for t, r in sorted(sigs.items(),
                       key=lambda kv: kv[1].get("paper_count", 0), reverse=True):
        if not r["has_data"]:
            print(f"  {t}  - no map entry")
            continue
        print(f"  {t}  papers={r['paper_count']}  cats={r['categories']}")
        for p in r["top_papers"][:3]:
            print(f"    [{p['published']}] {p['title']}")
            print(f"      {', '.join(p['authors'])}")
