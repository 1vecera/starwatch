"""Cached public web retrieval: plain HTTP first, Apify Website Content Crawler for JS-only pages."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx

from .common import BudgetExceeded, Cache, Ledger, atomic_write, digest, utcnow
from .text import Document, html_document, is_pdf, pdf_document, text_document

USER_AGENT = "Mozilla/5.0 (compatible; StarwatchCollector/1.0; +https://github.com/1vecera/starwatch)"
MAX_BYTES = 30 * 1024 * 1024
APIFY_API = "https://api.apify.com/v2"
CRAWLER = "apify~website-content-crawler"


def canonical(url: str) -> str:
    """Drop fragments, tracking parameters and consent wrappers so one page has one key."""
    parts = urlsplit(url.strip())
    if parts.path.endswith("nastaveni-souhlasu") and "url" in parse_qs(parts.query):
        return canonical(parse_qs(parts.query)["url"][0])
    query = "&".join(
        piece for piece in parts.query.split("&")
        if piece and not piece.lower().startswith(("utm_", "fbclid", "gclid", "dop_", "ref="))
    )
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), (parts.hostname or "").lower(), path, query, ""))


class Fetcher:
    """GET public URLs once, keep the bytes and response metadata in the cache."""

    def __init__(self, cache: Cache, timeout: float = 30.0, workers: int = 8, refetch_errors: bool = False):
        self.cache = cache
        self.timeout = timeout
        self.workers = workers
        self.refetch_errors = refetch_errors

    def _key(self, url: str) -> str:
        return digest({"get": url})

    def meta(self, url: str) -> dict:
        key = self._key(url)
        cached = self.cache.get("http", key)
        if cached and not (self.refetch_errors and cached.get("error") and not self.cache.offline):
            return cached
        self.cache.miss(url)
        record = {"url": url, "fetched_at": utcnow(), "via": "http"}
        try:
            with httpx.Client(
                follow_redirects=True, timeout=self.timeout,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "cs,en;q=0.5"},
            ) as client:
                with client.stream("GET", url) as response:
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError("response larger than 30 MB")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    record.update(
                        final_url=str(response.url), status=response.status_code,
                        content_type=response.headers.get("content-type", ""), bytes=len(body),
                        sha256=digest(body),
                    )
                    if response.status_code >= 400:
                        record["error"] = f"HTTP {response.status_code}"
                    else:
                        atomic_write(self.cache.path("http", key, ".body"), body)
        except (httpx.HTTPError, ValueError) as error:
            record["error"] = f"{type(error).__name__}: {str(error)[:200]}"
        self.cache.put("http", key, record)
        return record

    def fetch_many(self, urls: list[str]) -> dict[str, dict]:
        unique = sorted(set(urls))
        with ThreadPoolExecutor(self.workers) as pool:
            return dict(zip(unique, pool.map(self.meta, unique)))

    def document(self, url: str) -> Document | None:
        """Parsed document for a fetched URL, or the Apify-rendered text if one exists."""
        rendered = self.cache.get("render", digest({"render": url}))
        meta = self.meta(url)
        if meta.get("error") or not self.cache.path("http", self._key(url), ".body").exists():
            return self._rendered(rendered)
        body = self.cache.path("http", self._key(url), ".body").read_bytes()
        try:
            if is_pdf(body, meta.get("content_type")):
                return pdf_document(body, url, meta["fetched_at"])
            if "html" not in (meta.get("content_type") or "html") and b"<html" not in body[:2000].lower():
                return self._rendered(rendered)
            document = html_document(body, url, meta["fetched_at"])
        except Exception:  # noqa: BLE001 - unreadable bytes fall back to a rendering, if any
            return self._rendered(rendered)
        if rendered and rendered.get("text") and len(rendered["text"]) > document.chars:
            better = self._rendered(rendered)
            better.links = document.links
            return better
        return document

    @staticmethod
    def _rendered(record: dict | None) -> Document | None:
        if not record or not record.get("text"):
            return None
        return text_document(record["text"], record["url"], record.get("title", ""), record["fetched_at"], "apify")


class Renderer:
    """Render JavaScript-only pages with one batched Apify Website Content Crawler run."""

    def __init__(self, cache: Cache, ledger: Ledger, token: str | None = None, memory_mb: int = 4096,
                 timeout_s: int = 900):
        self.cache = cache
        self.ledger = ledger
        self.token = token if token is not None else os.environ.get("APIFY_TOKEN", "")
        self.memory_mb = memory_mb
        self.timeout_s = timeout_s

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def render(self, urls: list[str]) -> dict[str, dict]:
        wanted = sorted(set(urls))
        missing = [url for url in wanted if not self.cache.get("render", digest({"render": url}))]
        if missing:
            self.cache.miss(f"{len(missing)} renders")
            if not self.token:
                raise BudgetExceeded("APIFY_TOKEN is not set; cannot render JavaScript-only pages")
            # Upper bound: memory GB x timeout hours x $0.40 per compute unit.
            bound = self.memory_mb / 1024 * self.timeout_s / 3600 * 0.40
            self.ledger.check("apify", bound)
            self._run(missing)
        return {url: self.cache.get("render", digest({"render": url})) for url in wanted}

    def _run(self, urls: list[str]) -> None:
        run_input = {
            "startUrls": [{"url": url} for url in urls],
            "maxCrawlDepth": 0,
            "maxCrawlPages": len(urls),
            "maxResults": len(urls),
            "crawlerType": "playwright:adaptive",
            "removeCookieWarnings": True,
            "saveHtml": False,
            "saveMarkdown": False,
            "saveFiles": False,
            "proxyConfiguration": {"useApifyProxy": True},
        }
        started = utcnow()
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{APIFY_API}/acts/{CRAWLER}/runs",
                params={"memory": self.memory_mb, "timeout": self.timeout_s},
                headers=self._headers(), json=run_input,
            )
            response.raise_for_status()
            run = response.json()["data"]
            while run["status"] in {"READY", "RUNNING", "TIMING-OUT", "ABORTING"}:
                time.sleep(10)
                run = client.get(f"{APIFY_API}/actor-runs/{run['id']}", headers=self._headers()).json()["data"]
            cost = float(run.get("usageTotalUsd") or 0.0)
            self.ledger.record("apify", cost, {"run_id": run["id"], "actor": CRAWLER, "urls": len(urls),
                                               "status": run["status"]})
            items = client.get(
                f"{APIFY_API}/datasets/{run['defaultDatasetId']}/items",
                params={"clean": "true", "format": "json"}, headers=self._headers(),
            ).json()
        by_url = {}
        for item in items:
            for key in (item.get("url"), (item.get("crawl") or {}).get("loadedUrl")):
                if key:
                    by_url[canonical(key)] = item
        for url in urls:
            item = by_url.get(canonical(url))
            record = {"url": url, "fetched_at": started, "run_id": run["id"], "via": "apify"}
            if item and item.get("text"):
                record.update(text=item["text"], title=(item.get("metadata") or {}).get("title") or "",
                              loaded_url=(item.get("crawl") or {}).get("loadedUrl") or item.get("url"))
            else:
                record["error"] = f"no text from crawler run ({run['status']})"
            self.cache.put("render", digest({"render": url}), record)
