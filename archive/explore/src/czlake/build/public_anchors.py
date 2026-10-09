"""Fetch explicit public political anchors once; no searches or paid engine."""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import httpx
from lxml import html

from ..land import manifest_append, now_iso
from ..paths import RAW


def fetch(url: str) -> dict:
    root = RAW / "public_identity"
    root.mkdir(exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    saved = root / (key + ".json")
    if saved.exists():
        return json.loads(saved.read_text())
    try:
        response = httpx.get(url, follow_redirects=True, timeout=30)
        path = root / (key + ".html")
        path.write_bytes(response.content)
        # httpx honors the HTTP charset (UTF-8 by default); parsing bare bytes
        # as HTML can otherwise default to Latin-1 on Czech pages without meta.
        tree = html.fromstring(response.text)
        text = " ".join(tree.xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]"))
        links = [{"url": urljoin(str(response.url), x.get("href")), "label": " ".join(x.itertext()).strip()}
                 for x in tree.xpath("//a[@href]")]
        out = {"url": url, "final_url": str(response.url), "status": response.status_code,
               "observed_at": now_iso(), "path": str(path), "text": text, "links": links}
        saved.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        manifest_append({"source": "public_identity", "source_url": url, "final_url": str(response.url),
                         "fetched_at": out["observed_at"], "path": str(path), "bytes": len(response.content),
                         "sha256": hashlib.sha256(response.content).hexdigest()})
        return out
    except httpx.HTTPError as error:
        return {"url": url, "status": None, "error": type(error).__name__, "text": "", "links": []}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()
    if len(args.urls) > 20 or any(not url.startswith("https://") for url in args.urls):
        raise ValueError("An explicit batch of at most twenty HTTPS URLs is required")
    with ThreadPoolExecutor(max_workers=5) as pool:
        for out in pool.map(fetch, args.urls):
            print(json.dumps({key: out[key] for key in ["url", "status"]} | {
                "social_links": [x for x in out["links"] if "instagram.com/" in x["url"] or "facebook.com/" in x["url"]],
                "political_links": [x for x in out["links"] if any(term in x["url"] for term in ["kandidat", "zastupitel", "mestske-sdruzeni"])][:10]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
