"""Cached Exa search with spend accounting. Only titles, URLs, dates and short highlights are kept."""

from __future__ import annotations

import os
import time

import httpx

from .common import Cache, Ledger, digest, utcnow

EXA_URL = "https://api.exa.ai/search"
# Worst case for one search with highlights (observed $0.007-0.009 per call in October 2026).
SEARCH_BOUND_USD = 0.03


class Exa:
    def __init__(self, cache: Cache, ledger: Ledger, api_key: str | None = None):
        self.cache = cache
        self.ledger = ledger
        self.api_key = api_key if api_key is not None else os.environ.get("EXA_API_KEY", "")

    def search(self, query: str, *, num_results: int = 10, category: str | None = None,
               start: str | None = None, end: str | None = None, highlight_query: str | None = None,
               sentences: int = 2, per_url: int = 1) -> dict:
        """Run (or replay) one search. Returns ``{request, searched_at, results, cost_usd}``."""
        body: dict = {
            "query": query,
            "type": "auto",
            "numResults": num_results,
            "userLocation": "CZ",
            "contents": {"highlights": {"numSentences": sentences, "highlightsPerUrl": per_url}},
        }
        if highlight_query:
            body["contents"]["highlights"]["query"] = highlight_query
        if category:
            body["category"] = category
        if start:
            body["startPublishedDate"] = start
        if end:
            body["endPublishedDate"] = end
        key = digest(body)
        cached = self.cache.get("exa", key)
        if cached is not None:
            return cached
        self.cache.miss(f"exa search {query!r}")
        if not self.api_key:
            raise RuntimeError("EXA_API_KEY is not set")
        self.ledger.check("exa", SEARCH_BOUND_USD)
        data = self._post(body)
        cost = float((data.get("costDollars") or {}).get("total") or 0.0)
        self.ledger.record("exa", cost, {"query": query, "results": len(data.get("results") or [])})
        record = {
            "request": body,
            "searched_at": utcnow(),
            "cost_usd": cost,
            "results": [
                {
                    "url": item.get("url"),
                    "title": item.get("title") or "",
                    "published_date": item.get("publishedDate"),
                    "highlights": [h[:600] for h in (item.get("highlights") or [])],
                }
                for item in data.get("results") or []
                if item.get("url")
            ],
        }
        self.cache.put("exa", key, record)
        return record

    def _post(self, body: dict) -> dict:
        for attempt in range(4):
            response = httpx.post(EXA_URL, headers={"x-api-key": self.api_key}, json=body, timeout=90)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("unreachable")
