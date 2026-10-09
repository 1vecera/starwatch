"""Exact returned Facebook parent-post image provenance; no input echo or avatar selection."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse


_JSON_CACHE = OrderedDict()
_JSON_CACHE_LOCK = threading.Lock()
_JSON_CACHE_BYTES = 64 * 1024**2


def pinned_media_json(path):
    """Cache exact immutable bytes with stat consistency and a bounded raw-byte footprint."""
    path = Path(path).resolve()
    def fingerprint():
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    with _JSON_CACHE_LOCK:
        before = fingerprint()
        key = (str(path), before)
        result = _JSON_CACHE.get(key)
        if result is None:
            raw = path.read_bytes()
            result = hashlib.sha256(raw).hexdigest(), json.loads(raw)
            if fingerprint() != before:
                raise ValueError("Pinned media JSON changed while being read")
            if len(raw) <= _JSON_CACHE_BYTES:
                # Remove stale versions and oldest sources before retaining bytes.
                for old in list(_JSON_CACHE):
                    if old[0] == str(path):
                        del _JSON_CACHE[old]
                while _JSON_CACHE and (len(_JSON_CACHE) >= 16 or sum(k[1][2] for k in _JSON_CACHE) + len(raw) > _JSON_CACHE_BYTES):
                    _JSON_CACHE.popitem(last=False)
                _JSON_CACHE[key] = result
        elif fingerprint() != before:
            raise ValueError("Pinned media JSON changed during cached lookup")
        else:
            _JSON_CACHE.move_to_end(key)
        return result



def allowed_facebook_image_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme == "https" and (parsed.hostname or "").lower().endswith(".fbcdn.net")
                    and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        return False


def facebook_parent_identity(post):
    if not isinstance(post, dict):
        raise ValueError("Facebook source requires a returned parent post")
    raw_id = post.get("postId") or post.get("id")
    if type(raw_id) is int and raw_id > 0:
        raw_id = str(raw_id)
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ValueError("Facebook parent has no canonical post ID")
    user = post.get("user")
    owner = str(user.get("id", "")) if isinstance(user, dict) else ""
    if not owner.isdigit() or int(owner) <= 0:
        raise ValueError("Facebook parent has no exact returned numeric author")
    if not isinstance(post.get("topLevelUrl"), str):
        raise ValueError("Facebook returned parent container URL is absent")
    parsed = urlparse(post["topLevelUrl"])
    if (parsed.scheme != "https" or parsed.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"}
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path.rstrip("/") != f"/{owner}/posts/{raw_id}"):
        raise ValueError("Facebook returned author/container post mismatch")
    for field in ("pageId", "userId"):
        if post.get(field) is not None and str(post[field]) != owner:
            raise ValueError("Facebook returned author IDs conflict")
    for field in ("user", "owner", "author"):
        author = post.get(field)
        if not isinstance(author, dict):
            continue
        if author.get("id") is not None and str(author["id"]) != owner:
            raise ValueError("Facebook returned author IDs conflict")
        for name in ("profileUrl", "url"):
            if author.get(name) is not None:
                if not isinstance(author[name], str):
                    raise ValueError("Facebook returned author profile URL is malformed")
                profile = urlparse(author[name])
                if (profile.scheme != "https" or profile.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"}
                        or profile.username or profile.password or profile.port not in (None, 443)
                        or profile.path.rstrip("/") != "/" + owner):
                    raise ValueError("Facebook returned author profile mismatch")
    return "facebook:" + raw_id, "facebook:" + owner


def facebook_image_pointer_value(post, prefix, pointer, kind):
    if kind != "image" or not isinstance(pointer, str) or not pointer.startswith(prefix + "/"):
        raise ValueError("Facebook images require an exact parent media pointer")
    suffix = pointer[len(prefix) + 1:]
    if suffix in {"thumbnailUrl", "imageUrl"}:
        selected = post.get(suffix)
    else:
        match = re.fullmatch(r"media/([0-9]+)/(thumbnail|thumbnailUrl|imageUrl)", suffix)
        media = post.get("media")
        if not match or not isinstance(media, list) or int(match[1]) >= len(media):
            raise ValueError("Facebook pointer is not a returned post image field")
        entry = media[int(match[1])]
        if not isinstance(entry, dict):
            raise ValueError("Facebook media entry must be scalar source metadata")
        selected = entry.get(match[2])
    if not isinstance(selected, str):
        raise ValueError("Facebook source image field is absent")
    if not allowed_facebook_image_url(selected):
        raise ValueError("Facebook source image must be returned HTTPS fbcdn media")
    return selected


def validate_facebook_media_entry(post, prefix, entry):
    asset_id, owner = facebook_parent_identity(post)
    if asset_id != entry.get("asset_id") or owner != entry.get("owner_account_id"):
        raise ValueError("Facebook media differs from its exact parent asset/owner")
    evidence = entry.get("verified_asset_evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("path"), str) or not evidence["path"]:
        raise ValueError("Facebook images require a pinned verified graph asset snapshot")
    path = Path(evidence["path"]).resolve()
    snapshot_sha, assets = pinned_media_json(path)
    if snapshot_sha != evidence.get("sha256"):
        raise ValueError("Facebook verified graph asset snapshot changed")
    if not isinstance(assets, list):
        raise ValueError("Facebook verified graph snapshot must contain original asset rows")
    matches = [a for a in assets if isinstance(a, dict) and a.get("asset_id") == asset_id]
    if (len(matches) != 1 or matches[0].get("verification_status") != "verified_publication_owner"
            or matches[0].get("owner_account_id") != owner or matches[0].get("platform") != "facebook"):
        raise ValueError("Facebook parent owner was not admitted in verified graph snapshot")
    selected = facebook_image_pointer_value(post, prefix, entry.get("source_media_pointer"), entry.get("kind"))
    if selected != entry.get("url", entry.get("source_url")):
        raise ValueError("Facebook image differs from its exact returned source field")
    return owner
