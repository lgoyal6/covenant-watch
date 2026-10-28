"""Thin helpers over shared/edgar.py for EDGAR full-text search (efts.sec.gov).

All HTTP goes through shared.edgar (rate limit + cache). We build the efts URL
ourselves only to add the `ciks` filter, which edgar.full_text_search lacks.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from shared import edgar

from validation.text import doc_url

EFTS = "https://efts.sec.gov/LATEST/search-index"


@dataclass(frozen=True)
class Hit:
    cik: str  # 10-digit
    accession: str
    filename: str
    form: str  # root form, e.g. 10-Q
    file_type: str  # e.g. 10-Q, EX-10.1, EX-99.1
    file_date: str
    period_ending: str | None
    sic: str | None
    name: str
    items: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return doc_url(self.cik, self.accession, self.filename)


def search(query: str, *, forms: str | None = None, start: str | None = None, end: str | None = None,
           ciks: str | None = None, page_from: int = 0, cache: bool = False) -> tuple[int, list[Hit]]:
    params = {"q": f'"{query}"', "from": str(page_from)}
    if forms:
        params["forms"] = forms
    if start and end:
        params.update(dateRange="custom", startdt=start, enddt=end)
    if ciks:
        params["ciks"] = ciks
    url = str(httpx.URL(EFTS, params=params))
    try:
        data = edgar.get_json(url, use_cache=cache)
    except Exception:
        return 0, []
    total = data.get("hits", {}).get("total", {}).get("value", 0)
    out = []
    for h in data.get("hits", {}).get("hits", []):
        src = h["_source"]
        adsh, _, fname = h["_id"].partition(":")
        if not src.get("ciks"):
            continue
        name = (src.get("display_names") or [""])[0]
        out.append(Hit(
            cik=src["ciks"][0].zfill(10),
            accession=adsh,
            filename=fname,
            form=(src.get("root_forms") or [src.get("form", "")])[0],
            file_type=src.get("file_type") or "",
            file_date=src.get("file_date") or "",
            period_ending=src.get("period_ending"),
            sic=(src.get("sics") or [None])[0],
            name=name,
            items=tuple(src.get("items") or ()),
        ))
    return total, out


def search_all(query: str, *, max_pages: int = 3, **kw) -> list[Hit]:
    hits: list[Hit] = []
    for p in range(max_pages):
        total, page = search(query, page_from=p * 100, **kw)
        hits.extend(page)
        if not page or (p + 1) * 100 >= total:
            break
    return hits
