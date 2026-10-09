"""Raw landing: immutable downloads with a manifest row per file (source URL, fetch time, checksum)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import httpx

from .paths import MANIFEST, RAW

UA = "Mozilla/5.0 (X11; Linux x86_64) czlake/0.1 (local research; contact: owner)"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def manifest_append(row: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def land_url(url: str, source: str, filename: str | None = None, *, extract: bool = False,
             timeout: float = 120.0, overwrite: bool = False) -> Path:
    """Download url into raw/<source>/<filename>; append a manifest row. Returns the file path.

    Landings are immutable: if the file exists and overwrite is False, it is reused.
    """
    target_dir = RAW / source
    target_dir.mkdir(parents=True, exist_ok=True)
    name = filename or url.rstrip("/").split("/")[-1].split("?")[0] or "index.html"
    path = target_dir / name
    if path.exists() and not overwrite:
        return path
    with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": UA}) as c:
        r = c.get(url)
        r.raise_for_status()
        data = r.content
    path.write_bytes(data)
    row = {
        "source": source, "source_url": url, "final_url": str(r.url), "fetched_at": now_iso(),
        "path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "content_type": r.headers.get("content-type"), "apify_run_id": None,
    }
    manifest_append(row)
    if extract and zipfile.is_zipfile(path):
        out = target_dir / (path.stem + "_unz")
        out.mkdir(exist_ok=True)
        with zipfile.ZipFile(path) as z:
            z.extractall(out)
    return path


if __name__ == "__main__":
    # usage: python -m czlake.land <source> <url> [--extract]
    src, url = sys.argv[1], sys.argv[2]
    p = land_url(url, src, extract="--extract" in sys.argv)
    print(p)
