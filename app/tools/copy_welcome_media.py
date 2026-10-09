"""Copy the public welcome wall's images and videos from web/media/ into web/welcome/.

The welcome page (web/index.html, aliased as web/welcome.html) is the only public page, so
every file it shows must live in one folder that the edge can expose on its own. The page is
the single source of truth: this script copies exactly the `welcome/<file>` names it references.
Both folders hold collected material and stay out of Git. Run from app/:

    uv run --offline python tools/copy_welcome_media.py
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PAGE = WEB / "index.html"
SOURCE = WEB / "media"
TARGET = WEB / "welcome"
REF = re.compile(r"welcome/([0-9a-f]{8,64}\.(?:jpg|jpeg|png|webp|avif|mp4|webm))")


def main() -> int:
    names = sorted(set(REF.findall(PAGE.read_text(encoding="utf-8"))))
    if not names:
        print(f"No welcome/<file> references found in {PAGE}", file=sys.stderr)
        return 1
    missing = [n for n in names if not (SOURCE / n).is_file()]
    if missing:
        print(f"Missing in {SOURCE}: {', '.join(missing)}", file=sys.stderr)
        return 1
    TARGET.mkdir(exist_ok=True)
    copied = 0
    for name in names:
        src, dst = SOURCE / name, TARGET / name
        if dst.is_file() and dst.stat().st_size == src.stat().st_size:
            continue
        shutil.copyfile(src, dst)
        copied += 1
    stale = [p for p in TARGET.iterdir() if p.is_file() and p.name not in names]
    for p in stale:
        p.unlink()
    total = sum((TARGET / n).stat().st_size for n in names)
    print(f"{len(names)} welcome files ({copied} copied, {len(stale)} stale removed, {total / 1e6:.1f} MB) in {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
