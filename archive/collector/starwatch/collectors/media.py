"""Media helpers for collectors: true image sizes and capped video downloads.

S1 lays thumbnails out in their real aspect ratio, so every saved image gets its width and height
from the file header (JPEG, PNG, WebP, GIF) rather than from what a platform claims.
"""

from __future__ import annotations

import struct
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..models import Media
from .actors import MAX_VIDEO_BYTES

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0 Safari/537.36"
)


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from an image header, or None for an unknown format."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return width, height
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8 ":
            width, height = struct.unpack("<HH", data[26:30])
            return width & 0x3FFF, height & 0x3FFF
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8X":
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return width, height
        return None
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            length = int.from_bytes(data[index + 2 : index + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return width, height
            index += 2 + length
    return None


def with_size(media: Media, run_dir: Path) -> Media:
    """The same media with its real pixel size read from the saved file."""
    try:
        with (run_dir / media.path).open("rb") as handle:
            head = handle.read(256 * 1024)
    except OSError:
        return media
    size = image_size(head)
    if not size or not all(size):
        return media
    return media.model_copy(update={"width": size[0], "height": size[1]})


async def download_video(
    client: httpx.AsyncClient, url: str, run_dir: Path, stem: str, *, apify_token: str = ""
) -> Media | None:
    """Stream one video into media/<stem>.mp4, up to MAX_VIDEO_BYTES. None when it fails or is too big.

    The Apify token is sent only to api.apify.com (TikTok videos sit in the run's key-value store).
    """
    headers = {"User-Agent": BROWSER_UA}
    if apify_token and urlsplit(url).hostname == "api.apify.com":
        headers["Authorization"] = f"Bearer {apify_token}"
    relative = f"media/{stem}.mp4"
    target = run_dir / relative
    partial = target.with_suffix(".part")
    size = 0
    try:
        async with client.stream("GET", url, headers=headers, timeout=60) as response:
            response.raise_for_status()
            with partial.open("wb") as out:
                async for chunk in response.aiter_bytes(256 * 1024):
                    size += len(chunk)
                    if size > MAX_VIDEO_BYTES:
                        raise ValueError("video larger than the download cap")
                    out.write(chunk)
        if size < 10_000:
            raise ValueError("not a video")
        partial.replace(target)
        return Media(kind="video", path=relative, source_url=_public_url(url))
    except (httpx.HTTPError, ValueError, OSError):
        partial.unlink(missing_ok=True)
        return None


def _public_url(url: str) -> str:
    """Strip signatures and query strings: the stored source URL is a reference, not a key."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"
