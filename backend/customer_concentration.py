"""
customer_concentration.py - SEC EDGAR 10-K customer concentration extractor.

Two-tier strategy:
1. Primary: SEC EDGAR full-text search API (free, no key) → HTML regex extraction
2. Fallback: Anthropic Haiku ($0.001/ticker) - only when regex fails + ANTHROPIC_API_KEY set

Cache: data/edgar_cache/{TICKER}_10k.json - TTL 365 days

Public API:
    get_customer_concentration(ticker, force_refresh=False) -> dict
    {
        has_data: bool,
        top_customer: str | None,
        pct: float | None,
        all_customers: list[{name, pct}],
        filing_date: str | None,
        source: "regex" | "haiku" | None,
        note: str | None  # error/warning if has_data=False
    }

Customer concentration is BONUS ONLY - never disqualifies.
Failure (429, regex miss, no API key) → has_data=False, score factor = 0pts.
"""

from __future__ import annotations

import json
import os
import re
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "edgar_cache"
CACHE_TTL_DAYS = 365
EDGAR_BASE = "https://efts.sec.gov"
EDGAR_SEARCH = f"{EDGAR_BASE}/LATEST/search-index"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# SEC EDGAR fair-access policy requires a real contact in the User-Agent.
# Set SEC_CONTACT_EMAIL in .env to your email.
import os as _os
_SEC_UA = f"TraderAI research {_os.environ.get('SEC_CONTACT_EMAIL', 'set-SEC_CONTACT_EMAIL-in-env@example.com')}"
HEADERS = {
    "User-Agent": _SEC_UA,
    "Accept-Encoding": "gzip, deflate",
    "Host": "efts.sec.gov",
}
SUBMISSIONS_HEADERS = {
    "User-Agent": _SEC_UA,
    "Accept-Encoding": "gzip, deflate",
}
REQUEST_TIMEOUT = 15
RATE_LIMIT_SLEEP = 1.0  # polite delay between EDGAR calls

# ── Regex patterns for customer concentration sentences ──────────────────────
_CUSTOMER_PATTERNS = [
    # "... accounted for approximately 42% of our total revenue"
    re.compile(
        r"([A-Z][A-Za-z0-9&,\.\s\(\)]{2,60}?)\s+(?:accounted|represented|comprised)\s+for\s+"
        r"(?:approximately\s+)?(\d{1,3}(?:\.\d)?)\s*%\s+of\s+(?:our\s+)?(?:total\s+)?(?:net\s+)?(?:revenue|revenues|net\s+sales|sales)",
        re.IGNORECASE,
    ),
    # "... represented 35% of net revenue"
    re.compile(
        r"(\d{1,3}(?:\.\d)?)\s*%\s+of\s+(?:our\s+)?(?:total\s+)?(?:net\s+)?(?:revenue|revenues|net\s+sales|sales)"
        r"[^.]{0,80}?([A-Z][A-Za-z0-9&,\.\s\(\)]{2,50})",
        re.IGNORECASE,
    ),
    # "significant customer accounted for 28% of revenue"
    re.compile(
        r"(?:significant|major|largest|principal)\s+customer[^.]{0,40}?(\d{1,3}(?:\.\d)?)\s*%",
        re.IGNORECASE,
    ),
    # "concentration of revenue risk ... customer A ... 31%"
    re.compile(
        r"customer\s+[A-Z]\b[^.]{0,80}?(\d{1,3}(?:\.\d)?)\s*%",
        re.IGNORECASE,
    ),
]

# Known customer name aliases to normalize
_KNOWN_CUSTOMERS = {
    "amazon": "Amazon / AWS",
    "aws": "Amazon / AWS",
    "microsoft": "Microsoft / Azure",
    "azure": "Microsoft / Azure",
    "google": "Google / GCP",
    "alphabet": "Google / GCP",
    "u.s. government": "U.S. Government",
    "u.s. department of defense": "DoD",
    "department of defense": "DoD",
    "dod": "DoD",
    "u.s. air force": "U.S. Air Force",
    "u.s. army": "U.S. Army",
    "u.s. navy": "U.S. Navy",
    "apple": "Apple",
    "meta": "Meta",
    "federal government": "U.S. Government",
}


def _normalize_customer(name: str) -> str:
    lower = name.strip().lower()
    for key, normalized in _KNOWN_CUSTOMERS.items():
        if key in lower:
            return normalized
    # Title-case cleanup
    return " ".join(w.capitalize() for w in name.strip().split())


# ── Cache helpers ─────────────────────────────────────────────────────────────
def _cache_path(ticker: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{ticker.upper()}_10k.json"


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        extracted_at = datetime.fromisoformat(data.get("extracted_at", "2000-01-01"))
        if datetime.now() - extracted_at > timedelta(days=CACHE_TTL_DAYS):
            return None  # stale
        return data
    except Exception:
        return None


def _save_cache(ticker: str, payload: dict) -> None:
    payload["extracted_at"] = datetime.now().isoformat()
    try:
        _cache_path(ticker).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[CUSTOMER] Cache write failed for {ticker}: {e}")


# ── EDGAR CIK lookup ──────────────────────────────────────────────────────────
def _get_cik(ticker: str) -> Optional[int]:
    """Look up CIK number for ticker via EDGAR company search."""
    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&forms=10-K"
    try:
        r = requests.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar"
            f"?company=&CIK={ticker}&type=10-K&dateb=&owner=include&count=5&search_text=&action=getcompany&output=atom",
            headers=SUBMISSIONS_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            # Extract CIK from Atom feed
            m = re.search(r"CIK=(\d+)", r.text)
            if m:
                return int(m.group(1))
    except Exception as e:
        logger.debug(f"[CUSTOMER] CIK lookup failed for {ticker}: {e}")
    return None


def _get_cik_via_submissions(ticker: str) -> Optional[int]:
    """Alternative: use EDGAR company_tickers.json mapping."""
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SUBMISSIONS_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        for _k, v in data.items():
            if v.get("ticker", "").upper() == ticker.upper():
                return int(v["cik_str"])
    except Exception as e:
        logger.debug(f"[CUSTOMER] CIK submissions lookup failed for {ticker}: {e}")
    return None


# ── EDGAR 10-K filing fetcher ─────────────────────────────────────────────────
def _get_latest_10k_url(cik: int) -> Optional[tuple[str, str]]:
    """
    Returns (filing_url, filing_date) for latest 10-K.
    Uses SEC submissions API.
    """
    url = EDGAR_SUBMISSIONS.format(cik=cik)
    try:
        r = requests.get(url, headers=SUBMISSIONS_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 429:
            logger.warning("[CUSTOMER] EDGAR rate limited (429)")
            return None
        if r.status_code != 200:
            return None
        data = r.json()
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form in ("10-K", "10-K/A"):
                acc = accessions[i].replace("-", "")
                doc = primary_docs[i] if i < len(primary_docs) else ""
                date = dates[i] if i < len(dates) else ""
                filing_url = (
                    f"https://www.sec.gov/Archives/edgar/full-index/"
                    f"/{acc[:4]}/{acc[4:6]}/{acc[6:8]}/{acc}/{doc}"
                )
                # Better: use the index URL
                idx_url = (
                    f"https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&CIK={cik:010d}&type=10-K&dateb=&owner=include&count=1&search_text="
                )
                # Use accession-based URL directly
                htm_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
                )
                return htm_url, date
    except Exception as e:
        logger.debug(f"[CUSTOMER] 10-K URL fetch failed for CIK {cik}: {e}")
    return None


def _fetch_10k_text(filing_url: str) -> Optional[str]:
    """Download 10-K HTML and return text content (first 500KB)."""
    try:
        r = requests.get(
            filing_url,
            headers={**SUBMISSIONS_HEADERS, "Host": "www.sec.gov"},
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        if r.status_code == 429:
            logger.warning("[CUSTOMER] EDGAR rate limited on filing download")
            return None
        if r.status_code != 200:
            return None
        # Read first 500KB - customer concentration in first half of 10-K
        content = b""
        for chunk in r.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > 600_000:
                break
        text = content.decode("utf-8", errors="replace")
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text
    except Exception as e:
        logger.debug(f"[CUSTOMER] Filing download failed: {e}")
    return None


# ── Regex extraction ──────────────────────────────────────────────────────────
def _extract_via_regex(text: str) -> list[dict]:
    """
    Run all patterns against filing text.
    Returns list of {name, pct} sorted by pct desc, deduped.
    """
    hits: list[dict] = []
    seen_pcts: set[float] = set()

    for pat in _CUSTOMER_PATTERNS:
        for m in pat.finditer(text):
            groups = m.groups()
            # Find the numeric group
            pct_val = None
            name_val = None
            for g in groups:
                if g and re.match(r"^\d{1,3}(?:\.\d)?$", g.strip()):
                    try:
                        pct_val = float(g.strip())
                    except ValueError:
                        pass
                elif g and len(g.strip()) > 2 and not re.match(r"^\d", g.strip()):
                    name_val = g.strip()

            if pct_val is None:
                continue
            # Filter noise: customer pct must be 5-80% to be meaningful
            if not (5.0 <= pct_val <= 80.0):
                continue
            if pct_val in seen_pcts:
                continue
            seen_pcts.add(pct_val)

            name = _normalize_customer(name_val) if name_val else "Unnamed Customer"
            hits.append({"name": name, "pct": pct_val})

    # Sort by pct descending, take top 5
    hits.sort(key=lambda x: x["pct"], reverse=True)
    return hits[:5]


# ── Haiku fallback ────────────────────────────────────────────────────────────
def _extract_via_haiku(text: str, ticker: str) -> Optional[list[dict]]:
    """
    Use Anthropic Haiku to extract customer concentration from 10-K excerpt.
    Only called when regex fails + ANTHROPIC_API_KEY is set.
    Cost: ~$0.001/ticker.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("[CUSTOMER] No ANTHROPIC_API_KEY - skipping Haiku fallback")
        return None

    # Find most relevant excerpt (~2000 chars around "customer" concentration mentions)
    lower = text.lower()
    idx = lower.find("concentration")
    if idx == -1:
        idx = lower.find("significant customer")
    if idx == -1:
        idx = lower.find("major customer")
    if idx == -1:
        # Take middle section of filing (often where Risk Factors / MD&A lives)
        idx = len(text) // 3

    excerpt = text[max(0, idx - 500): idx + 2000]

    prompt = (
        f"From this SEC 10-K excerpt for ticker {ticker}, extract all customer concentration data.\n\n"
        f"EXCERPT:\n{excerpt}\n\n"
        f"Return ONLY valid JSON array (no explanation):\n"
        f'[{{"name": "Customer Name", "pct": 35.0}}, ...]\n'
        f"Rules:\n"
        f"- Only include customers with explicit percentage of revenue\n"
        f"- pct must be numeric (float)\n"
        f"- If no data found, return []\n"
        f"- Maximum 5 entries\n"
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Extract JSON array
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        if not isinstance(data, list):
            return None
        result = []
        for item in data:
            if isinstance(item, dict) and "pct" in item:
                pct = float(item["pct"])
                name = _normalize_customer(item.get("name", "Unknown"))
                if 5.0 <= pct <= 80.0:
                    result.append({"name": name, "pct": pct})
        result.sort(key=lambda x: x["pct"], reverse=True)
        return result[:5] if result else None
    except ImportError:
        logger.debug("[CUSTOMER] anthropic package not installed")
        return None
    except Exception as e:
        logger.warning(f"[CUSTOMER] Haiku extraction failed for {ticker}: {e}")
        return None


# ── EDGAR full-text search alternative ───────────────────────────────────────
def _search_edgar_fulltext(ticker: str) -> Optional[tuple[str, str]]:
    """
    Use EDGAR full-text search to find latest 10-K and return its document URL.
    Returns (htm_url, filing_date) or None.
    """
    # First: resolve CIK
    cik = _get_cik_via_submissions(ticker)
    if not cik:
        cik = _get_cik(ticker)
    if not cik:
        logger.debug(f"[CUSTOMER] Could not resolve CIK for {ticker}")
        return None

    time.sleep(RATE_LIMIT_SLEEP)
    result = _get_latest_10k_url(cik)
    return result


# ── Main public API ───────────────────────────────────────────────────────────
def get_customer_concentration(
    ticker: str, force_refresh: bool = False
) -> dict:
    """
    Returns customer concentration data from SEC 10-K.

    Result schema:
        has_data: bool
        top_customer: str | None
        pct: float | None          - top customer % of revenue
        all_customers: list        - [{name, pct}, ...]
        filing_date: str | None
        source: "regex" | "haiku" | None
        note: str | None           - error/status message
    """
    ticker = ticker.upper()

    # Check cache
    if not force_refresh:
        cached = _load_cache(ticker)
        if cached:
            logger.debug(f"[CUSTOMER] Cache hit: {ticker}")
            return cached

    _empty = {
        "ticker": ticker,
        "has_data": False,
        "top_customer": None,
        "pct": None,
        "all_customers": [],
        "filing_date": None,
        "source": None,
        "note": None,
    }

    # Step 1: Get 10-K filing URL from EDGAR
    logger.info(f"[CUSTOMER] Fetching EDGAR 10-K for {ticker}...")
    try:
        result = _search_edgar_fulltext(ticker)
    except requests.exceptions.Timeout:
        _empty["note"] = "EDGAR timeout"
        _save_cache(ticker, _empty)
        return _empty
    except requests.exceptions.ConnectionError:
        _empty["note"] = "EDGAR connection error"
        _save_cache(ticker, _empty)
        return _empty

    if not result:
        _empty["note"] = "Could not locate 10-K filing"
        _save_cache(ticker, _empty)
        return _empty

    filing_url, filing_date = result

    # Step 2: Download filing text
    time.sleep(RATE_LIMIT_SLEEP)
    text = _fetch_10k_text(filing_url)
    if not text:
        _empty["note"] = "10-K download failed or rate limited"
        _save_cache(ticker, _empty)
        return _empty

    # Step 3: Regex extraction
    customers = _extract_via_regex(text)

    source = None
    if customers:
        source = "regex"
        logger.info(f"[CUSTOMER] {ticker}: regex found {len(customers)} customer(s)")
    else:
        # Step 4: Haiku fallback
        logger.info(f"[CUSTOMER] {ticker}: regex found nothing - trying Haiku...")
        haiku_result = _extract_via_haiku(text, ticker)
        if haiku_result:
            customers = haiku_result
            source = "haiku"
            logger.info(f"[CUSTOMER] {ticker}: Haiku found {len(customers)} customer(s)")
        else:
            logger.info(f"[CUSTOMER] {ticker}: No customer concentration data found")

    payload: dict = {
        "ticker": ticker,
        "has_data": bool(customers),
        "top_customer": customers[0]["name"] if customers else None,
        "pct": customers[0]["pct"] if customers else None,
        "all_customers": customers,
        "filing_date": filing_date,
        "source": source,
        "note": None,
    }

    _save_cache(ticker, payload)
    return payload


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["BBAI"]
    force = "--refresh" in tickers
    if force:
        tickers = [t for t in tickers if t != "--refresh"]

    for ticker in tickers:
        print(f"\n{'─'*50}")
        result = get_customer_concentration(ticker, force_refresh=force)
        if result["has_data"]:
            print(f"  {ticker} - Customer Concentration ({result['source'].upper()})")
            print(f"  Filing date : {result['filing_date']}")
            print(f"  Top customer: {result['top_customer']} ({result['pct']:.1f}% of revenue)")
            if len(result["all_customers"]) > 1:
                print("  All customers found:")
                for c in result["all_customers"]:
                    print(f"    • {c['name']}: {c['pct']:.1f}%")
        else:
            print(f"  {ticker} - No data ({result.get('note', 'regex + haiku both found nothing')})")
        print(f"{'─'*50}")
