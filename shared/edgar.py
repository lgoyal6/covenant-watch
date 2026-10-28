"""Minimal SEC EDGAR client shared by contracts/ and engine/ + validation/.

SEC requires a descriptive User-Agent with contact info and limits clients to
10 requests/second. Responses are cached on disk by URL hash; the cache is
append-only, so both sides can write it safely.
"""

import hashlib
import json
import os
import threading
import time

import httpx

from shared.paths import CACHE

USER_AGENT = os.environ.get("SEC_USER_AGENT", "Covenant Watch research contact@example.com")
MAX_RPS = 8  # stay under SEC's 10 requests/second

_lock = threading.Lock()
_last = 0.0


def _throttle() -> None:
    global _last
    with _lock:
        wait = _last + 1 / MAX_RPS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()


def _cache_path(url: str):
    return CACHE / hashlib.sha256(url.encode()).hexdigest()


def get(url: str, *, use_cache: bool = True, retries: int = 3) -> bytes:
    path = _cache_path(url)
    if use_cache and path.exists():
        return path.read_bytes()
    for attempt in range(retries):
        _throttle()
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
        if resp.status_code == 200:
            CACHE.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(resp.content)
            tmp.replace(path)
            return resp.content
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(2**attempt)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"EDGAR request failed after {retries} attempts: {url}")


def get_json(url: str, **kw) -> dict:
    return json.loads(get(url, **kw))


def company_facts(cik: str) -> dict:
    """XBRL facts for one company (data.sec.gov companyfacts API)."""
    return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json")


def submissions(cik: str) -> dict:
    """Filing history for one company (data.sec.gov submissions API)."""
    return get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")


def full_text_search(query: str, *, forms: str | None = None, start: str | None = None, end: str | None = None, page_from: int = 0) -> dict:
    """EDGAR full-text search (efts.sec.gov). Dates are YYYY-MM-DD."""
    params = {"q": f'"{query}"', "from": str(page_from)}
    if forms:
        params["forms"] = forms
    if start and end:
        params.update(dateRange="custom", startdt=start, enddt=end)
    url = str(httpx.URL("https://efts.sec.gov/LATEST/search-index", params=params))
    return get_json(url, use_cache=False)
