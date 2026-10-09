"""Fetch TikTok's own Czech subtitle tracks (ASR/creator captions) linked from Apify TikTok items.

The CDN links expire within hours, so this runs right after each TikTok collection. Stored per video
under raw/tiktok_subtitles/<video_id>.<lang>.vtt with a manifest row.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from ..land import UA, manifest_append, now_iso
from ..paths import RAW

OUT = RAW / "tiktok_subtitles"


def fetch_for(raw_json: Path, langs=("ces-CZ", "slk-SK")) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    d = json.loads(raw_json.read_text())
    got = miss = 0
    with httpx.Client(headers={"User-Agent": UA, "Referer": "https://www.tiktok.com/"}, follow_redirects=True, timeout=30) as c:
        for it in d["items"]:
            for s in (it.get("videoMeta") or {}).get("subtitleLinks") or []:
                if s.get("language") not in langs:
                    continue
                p = OUT / f"{it['id']}.{s['language']}.{s.get('source','x')}.vtt"
                if p.exists():
                    continue
                try:
                    r = c.get(s["downloadLink"])
                    r.raise_for_status()
                    p.write_bytes(r.content)
                    manifest_append({"source": "tiktok_subtitles", "source_url": it.get("webVideoUrl"),
                                     "final_url": s["downloadLink"][:200], "fetched_at": now_iso(), "path": str(p),
                                     "bytes": len(r.content), "sha256": None, "content_type": "text/vtt",
                                     "apify_run_id": d.get("run_id"), "subtitle_source": s.get("source")})
                    got += 1
                except Exception:  # noqa: BLE001
                    miss += 1
    return {"fetched": got, "failed": miss}


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(a, fetch_for(Path(a)))
