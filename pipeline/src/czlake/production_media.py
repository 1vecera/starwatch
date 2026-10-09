"""Retain bounded public media bytes from source-bound Instagram CDN metadata."""
from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from czlake.production_budget import atomic_write, canonical, digest, file_hash
from czlake.production_collect import public_metadata
from czlake.production_facebook_media import allowed_facebook_image_url, pinned_media_json, validate_facebook_media_entry

from czlake.production_new_platforms import NEW_ACTORS, allowed_new_media_url, source_input, validate_new_media_entry

MAX_FILES = 60
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_CUMULATIVE_BYTES = 50 * 1024**3
MAX_REQUEST_SECONDS = 45
RUN_DEADLINE = None


def allowed_url(url: object) -> bool:
    if allowed_new_media_url(url):
        return True
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return bool(parsed.scheme == "https" and port in (None, 443)
                and not parsed.username and not parsed.password
                and any(host.endswith("." + domain) for domain in ("cdninstagram.com", "fbcdn.net")))


class MediaRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError("Media redirect left the allowlisted public CDN")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def media_type(prefix: bytes, kind: str) -> str:
    if kind == "video" and len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        return "video/mp4"
    if kind == "image":
        if prefix.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
            return "image/webp"
    raise ValueError("Downloaded bytes do not match the planned media kind")


def media_pointer_value(post: dict, prefix: str, pointer: str, kind: str) -> str:
    """Resolve only media fields beneath the exact selected parent post."""
    if not isinstance(pointer, str) or not pointer.startswith(prefix + "/"):
        raise ValueError("Media pointer leaves its exact source post")
    parts = pointer[len(prefix) + 1:].split("/")
    value, depth = post, 0
    while len(parts) >= 2 and parts[0] == "childPosts":
        depth += 1
        if depth > 3 or not parts[1].isdigit():
            raise ValueError("Media child pointer exceeds public source policy")
        values = value.get("childPosts", [])
        index = int(parts[1])
        if index >= len(values):
            raise ValueError("Media child pointer index invalid")
        value, parts = values[index], parts[2:]
    if kind == "image" and len(parts) == 2 and parts[0] == "images" and parts[1].isdigit():
        values = value.get("images", [])
        index = int(parts[1])
        if index >= len(values):
            raise ValueError("Media image-list pointer index invalid")
        return values[index]
    field = "videoUrl" if kind == "video" else "displayUrl"
    if parts != [field]:
        raise ValueError("Media pointer is not a public media field")
    return value.get(field)


def validate_plan(plan: dict) -> list[dict]:
    if plan.get("schema_version") != "production-media-plan-v1":
        raise ValueError("Unknown media plan")
    entries = plan.get("entries")
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_FILES:
        raise ValueError("Media plan exceeds file bound")
    seen, envelopes = set(), {}
    for item in entries:
        if not isinstance(item, dict) or item.get("kind") not in {"image", "video"}:
            raise ValueError("Malformed media entry")
        if not allowed_url(item.get("url")) or not isinstance(item.get("asset_id"), str):
            raise ValueError("Only source-bound public CDN media is allowed")
        exception_ref = item.get("file_bound_evidence")
        if exception_ref:
            exception_path = Path(exception_ref["path"]).resolve()
            if file_hash(exception_path) != exception_ref["sha256"]:
                raise ValueError("Media byte-bound exception evidence changed")
            exception = json.loads(exception_path.read_text())
            media_id = "media:" + digest([item["asset_id"], item["kind"], item["url"]])[:24]
            matching = [r for r in exception.get("evidence", [])
                        if r.get("media_id") == media_id and r.get("asset_id") == item["asset_id"]]
            if (exception.get("schema_version") != "public-media-byte-bound-exception-v1"
                    or not 30 * 1024**2 < exception.get("file_byte_bound", 0) <= 64 * 1024**2
                    or exception.get("maximum_files") != 2 or len(matching) != 1
                    or not 30 * 1024**2 < matching[0].get("declared_bytes", 0) <= exception["file_byte_bound"]):
                raise ValueError("Media byte-bound exception is not exact independently observed evidence")
        source = Path(item["source_envelope"]).resolve()
        if source not in envelopes:
            envelopes[source] = pinned_media_json(source)
        sha, envelope = envelopes[source]
        if (sha != item["source_envelope_sha256"] or envelope.get("policy_version") != "public-metadata-v1"
                or envelope.get("schema_version") != 1
                or envelope.get("actor") not in {"apify/instagram-scraper", "apify/instagram-profile-scraper", "apify/facebook-posts-scraper", *NEW_ACTORS}):
            raise ValueError("Source envelope changed or was not allowlisted")
        index = item["source_item_index"]
        if type(index) is not int or not 0 <= index < len(envelope["items"]):
            raise ValueError("Source item index invalid")
        original = envelope["items"][index]
        lineage = envelope.get("original_source")
        if lineage:
            ancestor = Path(lineage["path"]).resolve()
            if file_hash(ancestor) != lineage["sha256"]:
                raise ValueError("Original cached source envelope changed")
            ancestor_doc = json.loads(ancestor.read_text())
            if ancestor_doc.get("actor") != envelope.get("actor"):
                raise ValueError("Sanitized cached source actor changed")
            expected = public_metadata(envelope["actor"], ancestor_doc["items"][index])
            if expected != original:
                raise ValueError("Sanitized source is not exact original public projection")
        prefix = f"/items/{index}"
        if envelope.get("actor") == "apify/instagram-profile-scraper":
            post_index = item.get("source_post_index")
            if original.get("private") is not False or type(post_index) is not int:
                raise ValueError("Cached media requires a public profile and exact post index")
            if not 0 <= post_index < len(original.get("latestPosts", [])):
                raise ValueError("Cached source post index invalid")
            original = original["latestPosts"][post_index]
            prefix += f"/latestPosts/{post_index}"
        if envelope.get("actor") in NEW_ACTORS:
            validate_new_media_entry(envelope["actor"], original, prefix, item, source_input(envelope))
            key = (item["asset_id"], item["kind"], item["url"])
            if key in seen:
                raise ValueError("Duplicate asset media in bounded plan")
            seen.add(key)
            continue
        if envelope.get("actor") == "apify/facebook-posts-scraper":
            validate_facebook_media_entry(original, prefix, item)
            key = (item["asset_id"], item["kind"], item["url"])
            if key in seen:
                raise ValueError("Duplicate asset media in bounded plan")
            seen.add(key)
            continue
        field = "videoUrl" if item["kind"] == "video" else "displayUrl"
        resolved = media_pointer_value(original, prefix, item["source_media_pointer"], item["kind"]) if item.get("source_media_pointer") else original.get(field)
        if resolved != item["url"] or "instagram:" + str(original.get("id")) != item["asset_id"]:
            raise ValueError("Media does not match its exact source asset")
        key = (item["asset_id"], item["kind"], item["url"])
        if key in seen:
            raise ValueError("Duplicate asset media in bounded plan")
        seen.add(key)
    return entries


def entry_final_url_allowed(entry, value):
    platform = entry["asset_id"].split(":", 1)[0]
    if platform in {"youtube", "x", "tiktok"}:
        return allowed_new_media_url(value, platform)
    return allowed_facebook_image_url(value) if entry["asset_id"].startswith("facebook:") else allowed_url(value)


def validate_checkpoint_rows(rows, entries, *, complete=False):
    if not isinstance(rows, list) or len(rows) > len(entries) or complete and len(rows) != len(entries):
        raise ValueError("Media checkpoint is not a sequential exact-plan checkpoint")
    for row, item in zip(rows, entries):
        if (row.get("status") not in {"downloaded", "failed", "skipped"}
                or row.get("source_url") != item["url"]
                or row.get("media_id") != "media:" + digest([item["asset_id"], item["kind"], item["url"]])[:24]
                or any(row.get(k) != item.get(k) for k in ("asset_id", "kind", "source_envelope",
                    "source_envelope_sha256", "source_item_index", "source_post_index", "source_media_pointer", "file_bound_evidence", "owner_account_id", "verified_asset_evidence"))):
            raise ValueError("Media checkpoint record differs from its exact plan entry")
        if row["status"] == "downloaded":
            path = Path(row["path"])
            if (file_hash(path) != row["sha256"] or path.stat().st_size != row["bytes"]
                    or row["bytes"] <= 0 or not entry_final_url_allowed(item, row.get("final_url"))):
                raise ValueError("Previously retained media changed")
            with path.open("rb") as stream:
                if media_type(stream.read(32), row["kind"]) != row["content_type"]:
                    raise ValueError("Previously retained media type changed")
        elif any(row.get(k) is not None for k in ("path", "sha256", "bytes")):
            raise ValueError("Failed/skipped media cannot claim retained bytes")


def retain(plan_path: Path, output: Path, *, opener=None, total_byte_bound=None,
           run_deadline=None, request_seconds=None, reusable_records=None, blob_root=None) -> dict:
    """One writer, sequential bounded GETs; every record distinguishes bytes from URLs."""
    plan = json.loads(plan_path.read_text())
    entries = validate_plan(plan)
    total_byte_bound = MAX_TOTAL_BYTES if total_byte_bound is None else total_byte_bound
    request_seconds = MAX_REQUEST_SECONDS if request_seconds is None else request_seconds
    if type(total_byte_bound) is not int or not 0 < total_byte_bound <= MAX_TOTAL_BYTES:
        raise ValueError("Invalid bounded plan transfer allocation")
    if not isinstance(request_seconds, (int, float)) or not 0 < request_seconds <= MAX_REQUEST_SECONDS:
        raise ValueError("Invalid request deadline")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    blob_root = Path(blob_root).resolve() if blob_root else output
    blob_root.mkdir(parents=True, exist_ok=True)
    index_path = output / "index.json"
    plan_hash = file_hash(plan_path)
    if index_path.exists():
        prior = json.loads(index_path.read_text())
        if prior["plan_sha256"] != plan_hash:
            raise ValueError("Existing media checkpoint belongs to another plan")
        validate_checkpoint_rows(prior["records"], entries, complete=True)
        return prior
    opener = opener or urllib.request.build_opener(MediaRedirect())
    progress_path = output / "progress.json"
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {}
    if progress and progress.get("plan_sha256") != plan_hash:
        raise ValueError("Existing media progress belongs to another plan")
    rows = progress.get("records", [])
    validate_checkpoint_rows(rows, entries)
    total = sum(row.get("bytes", 0) for row in rows)
    transferred = progress.get("transferred_bytes", total)
    reusable_records = reusable_records or {}
    for item in entries[len(rows):]:
        row = {k: item[k] for k in ("asset_id", "kind", "source_envelope", "source_envelope_sha256", "source_item_index")}
        for name in ("owner_account_id", "verified_asset_evidence"):
            if name in item:
                row[name] = item[name]
        if "source_post_index" in item:
            row["source_post_index"] = item["source_post_index"]
        if "source_media_pointer" in item:
            row["source_media_pointer"] = item["source_media_pointer"]
        row.update(media_id="media:" + digest([item["asset_id"], item["kind"], item["url"]])[:24],
                   source_url=item["url"], status="not_downloaded", fetched_at=datetime.now(UTC).isoformat())
        file_bound = MAX_FILE_BYTES
        if item.get("file_bound_evidence"):
            exception = json.loads(Path(item["file_bound_evidence"]["path"]).read_text())
            file_bound = exception["file_byte_bound"]
        row["file_byte_bound"] = file_bound
        if "file_bound_evidence" in item:
            row["file_bound_evidence"] = item["file_bound_evidence"]
        reused = reusable_records.get(row["media_id"])
        if reused and reused.get("status") == "downloaded":
            if (file_hash(Path(reused["path"])) != reused["sha256"]
                    or Path(reused["path"]).stat().st_size != reused["bytes"]
                    or reused.get("asset_id") != item["asset_id"] or reused.get("kind") != item["kind"]
                    or reused.get("source_url") != item["url"] or not entry_final_url_allowed(item, reused.get("final_url"))):
                raise ValueError("Reusable media differs from its exact asset/URL/hash")
            with Path(reused["path"]).open("rb") as stream:
                if media_type(stream.read(32), item["kind"]) != reused["content_type"]:
                    raise ValueError("Reusable media type differs from its actual bytes")
            row.update({k: reused[k] for k in ("status", "path", "sha256", "bytes", "content_type", "final_url", "fetched_at")})
            row["reused_verified_bytes"] = True
            total += row["bytes"]
            rows.append(row)
            atomic_write(progress_path, canonical({"plan_sha256": plan_hash, "records": rows,
                                                  "transferred_bytes": transferred}) + b"\n")
            continue
        remaining = min(file_bound, total_byte_bound - transferred)
        if remaining <= 0:
            row.update(status="skipped", reason="total_byte_bound")
            rows.append(row)
            continue
        temporary = None
        try:
            deadline = min(time.monotonic() + request_seconds, run_deadline or RUN_DEADLINE or float("inf"))
            if deadline <= time.monotonic():
                row.update(status="skipped", reason="run_deadline")
                rows.append(row)
                atomic_write(progress_path, canonical({"plan_sha256": plan_hash, "records": rows,
                                                      "transferred_bytes": transferred}) + b"\n")
                continue
            request = urllib.request.Request(item["url"], headers={"User-Agent": "Starwatch-public-evidence/1.0"})
            with opener.open(request, timeout=min(8, max(0.1, deadline - time.monotonic()))) as response:
                if not entry_final_url_allowed(item, response.geturl()):
                    raise ValueError("Final media URL outside public CDN allowlist")
                declared = response.headers.get("Content-Length")
                declared = int(declared) if declared is not None else None
                if declared is not None and (declared < 0 or declared > remaining):
                    raise ValueError("Media exceeds remaining byte bound")
                fd, temporary = tempfile.mkstemp(prefix=".media-", dir=output)
                sha, size, prefix = hashlib.sha256(), 0, b""
                with os.fdopen(fd, "wb") as stream:
                    while True:
                        timeout = deadline - time.monotonic()
                        if timeout <= 0:
                            raise ValueError("Media exceeds streaming deadline")
                        transport = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                        if transport is not None:
                            transport.settimeout(min(8, timeout))
                        block = response.read(min(65536, remaining + 1 - size))
                        if not block:
                            break
                        size += len(block)
                        transferred += len(block)
                        if size > remaining or time.monotonic() > deadline:
                            raise ValueError("Media exceeds streaming byte bound")
                        prefix = (prefix + block)[:32]
                        sha.update(block)
                        stream.write(block)
                    if declared is not None and size != declared:
                        raise ValueError("Media byte count differs from declared Content-Length")
                    content_type = media_type(prefix, item["kind"])
                    stream.flush()
                    os.fsync(stream.fileno())
                target = blob_root / (sha.hexdigest() + {"video/mp4": ".mp4", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type])
                os.replace(temporary, target)
                temporary = None
                total += size
                row.update(status="downloaded", path=str(target), sha256=sha.hexdigest(), bytes=size,
                           content_type=content_type, final_url=response.geturl())
        except (OSError, ValueError, urllib.error.URLError) as error:
            row.update(status="failed", error_type=type(error).__name__)
            if isinstance(error, ValueError):
                row["reason"] = str(error)
            if isinstance(error, urllib.error.HTTPError):
                row["http_status"] = error.code
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        rows.append(row)
        atomic_write(progress_path, canonical({"plan_sha256": plan_hash, "records": rows,
                                              "transferred_bytes": transferred}) + b"\n")
    result = {"schema_version": "production-media-v1", "plan_sha256": plan_hash,
              "observed_at": datetime.now(UTC).isoformat(), "records": rows,
              "summary": {"planned": len(entries), "downloaded": sum(r["status"] == "downloaded" for r in rows),
                          "bytes": total, "transferred_bytes": transferred,
                          "file_byte_bound": MAX_FILE_BYTES, "total_byte_bound": total_byte_bound}}
    atomic_write(index_path, canonical(result) + b"\n")
    return result


def retain_many(plan_paths, output: Path, *, base_index=None, workers=16,
                cumulative_byte_bound=MAX_CUMULATIVE_BYTES, deadline_seconds=1200,
                opener=None) -> dict:
    """One locked writer with durable transfer reservations and immutable plans.

    Interrupted active plans retain a conservative one-file uncertainty hold;
    completed indexes reconcile their exact transferred-byte checkpoint.
    """
    if type(cumulative_byte_bound) is not int or not 0 < cumulative_byte_bound <= MAX_CUMULATIVE_BYTES:
        raise ValueError("Invalid cumulative public transfer cap")
    if type(workers) is not int or not 1 <= workers <= 32:
        raise ValueError("Bounded GET worker count must be between1 and32")
    if not isinstance(deadline_seconds, (int, float)) or not 0 < deadline_seconds <= 1800:
        raise ValueError("Bounded media run must finish within30minutes")
    plans = [Path(p).resolve() for p in plan_paths]
    if not plans or len(set(plans)) != len(plans):
        raise ValueError("Explicit unique plan paths required")
    plan_hashes = {p: file_hash(p) for p in plans}
    if len(set(plan_hashes.values())) != len(plans):
        raise ValueError("Duplicate plan content hashes would share one transfer reservation")
    entries = {p: validate_plan(json.loads(p.read_text())) for p in plans}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    base = json.loads(Path(base_index).read_text()) if base_index else {"records": [], "summary": {}}
    for row in base["records"]:
        if row["status"] == "downloaded" and file_hash(Path(row["path"])) != row["sha256"]:
            raise ValueError("Base media bytes changed")
    base_sha = file_hash(Path(base_index)) if base_index else None
    base_transfer = base.get("summary", {}).get("transferred_bytes", base.get("summary", {}).get("bytes", 0))
    if type(base_transfer) is not int or base_transfer < 0:
        raise ValueError("Invalid original transfer checkpoint")
    deadline = time.monotonic() + deadline_seconds
    budget_path = output / "transfer-budget.json"

    with (output / ".media-run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget = json.loads(budget_path.read_text()) if budget_path.exists() else {
            "schema_version": "production-media-transfer-budget-v1", "cumulative_byte_bound": cumulative_byte_bound,
            "base_index_sha256": base_sha, "base_transferred_bytes": base_transfer, "plans": {}}
        if (budget.get("schema_version") != "production-media-transfer-budget-v1"
                or budget.get("cumulative_byte_bound") != cumulative_byte_bound
                or budget.get("base_index_sha256") != base_sha):
            raise ValueError("Media transfer ledger belongs to another cap/base")
        current = {}
        reusable = {r["media_id"]: r for r in base["records"] if r["status"] == "downloaded"}
        for p in plans:
            sha = file_hash(p)
            directory = output / "plans" / sha
            record = budget["plans"].setdefault(sha, {"plan": str(p), "state": "pending",
                                                    "transferred_bytes": 0, "uncertain_bytes": 0, "reserved_bytes": 0})
            record["output"] = str(directory)
            checkpoint = directory / "index.json"
            progress = directory / "progress.json"
            if checkpoint.exists():
                prior = retain(p, directory, opener=object())
                current[sha] = prior
                reusable.update({r["media_id"]: r for r in prior["records"] if r["status"] == "downloaded"})
                record.update(state="complete", transferred_bytes=prior["summary"]["transferred_bytes"], reserved_bytes=0)
            elif record["state"] == "reserved":
                # At most one streaming file can escape its per-file checkpoint.
                # Keep this hold on every restart until a caller can reconcile it.
                maximum = max((64 * 1024**2 if e.get("file_bound_evidence") else MAX_FILE_BYTES) for e in entries[p])
                record["uncertain_bytes"] += maximum
                previous = json.loads(progress.read_text()) if progress.exists() else {}
                record.update(state="pending", reserved_bytes=0,
                              transferred_bytes=previous.get("transferred_bytes", 0))
        # The aggregate is durable even when callers append only new plan paths.
        # Re-read ledger-owned checkpoints, rather than silently losing media
        # resources whose original completed plan was omitted from this call.
        for sha, record in budget["plans"].items():
            if sha in current or sha in plan_hashes.values():
                continue
            old_plan = Path(record["plan"])
            if file_hash(old_plan) != sha:
                raise ValueError("Ledger-owned immutable media plan changed")
            old_entries = validate_plan(json.loads(old_plan.read_text()))
            directory = Path(record["output"])
            if (directory / "index.json").exists():
                prior = retain(old_plan, directory, opener=object())
                current[sha] = prior
                reusable.update({r["media_id"]: r for r in prior["records"] if r["status"] == "downloaded"})
                record.update(state="complete", transferred_bytes=prior["summary"]["transferred_bytes"], reserved_bytes=0)
            else:
                progress_path = directory / "progress.json"
                prior = json.loads(progress_path.read_text()) if progress_path.exists() else {}
                if prior and prior.get("plan_sha256") != sha:
                    raise ValueError("Ledger-owned media progress belongs to another plan")
                rows = prior.get("records", [])
                validate_checkpoint_rows(rows, old_entries)
                current[sha] = {"records": rows}
                reusable.update({r["media_id"]: r for r in rows if r["status"] == "downloaded"})
                if record["state"] == "reserved":
                    record["uncertain_bytes"] += max((64 * 1024**2 if e.get("file_bound_evidence") else MAX_FILE_BYTES) for e in old_entries)
                    record.update(state="pending", reserved_bytes=0, transferred_bytes=prior.get("transferred_bytes", 0))
        def save_budget():
            atomic_write(budget_path, canonical(budget) + b"\n")
        def usage():
            return budget["base_transferred_bytes"] + sum(
                r["transferred_bytes"] + r["uncertain_bytes"] + r["reserved_bytes"] for r in budget["plans"].values())
        if usage() > cumulative_byte_bound:
            raise ValueError("Existing media transfers/reservations exceed cumulative bound")
        save_budget()
        pending = [p for p in plans if budget["plans"][file_hash(p)]["state"] != "complete"]
        while pending and time.monotonic() < deadline:
            group = []
            for p in pending[:workers]:
                sha = file_hash(p)
                record = budget["plans"][sha]
                remaining = cumulative_byte_bound - usage()
                possible = MAX_TOTAL_BYTES - record["transferred_bytes"]
                allocation = min(possible, max(0, remaining - 1))
                if allocation <= 0:
                    break
                record.update(state="reserved", reserved_bytes=allocation + 1)
                group.append((p, sha, record["transferred_bytes"] + allocation))
            if not group:
                break
            save_budget()  # Reserve before any public GET is launched.
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(group)) as pool:
                futures = [(sha, pool.submit(retain, p, Path(budget["plans"][sha]["output"]),
                                            opener=opener, total_byte_bound=allocation,
                                            run_deadline=deadline, reusable_records=reusable,
                                            blob_root=output / "blobs")) for p, sha, allocation in group]
                for sha, future in futures:
                    result = future.result()
                    current[sha] = result
                    reusable.update({r["media_id"]: r for r in result["records"] if r["status"] == "downloaded"})
                    budget["plans"][sha].update(state="complete", transferred_bytes=result["summary"]["transferred_bytes"], reserved_bytes=0)
                    save_budget()
            pending = pending[len(group):]
        records, positions, prior_attempts = list(base["records"]), {}, []
        for index, row in enumerate(records):
            if row["media_id"] in positions:
                raise ValueError("Duplicate base media identifiers")
            positions[row["media_id"]] = index
        for sha, result in current.items():
            for row in result["records"]:
                if row["media_id"] not in positions:
                    positions[row["media_id"]] = len(records)
                    records.append(row)
                elif records[positions[row["media_id"]]] != row:
                    previous = records[positions[row["media_id"]]]
                    if previous["status"] != "downloaded" and row["status"] == "downloaded":
                        prior_attempts.append(previous)
                        records[positions[row["media_id"]]] = row
                    else:
                        prior_attempts.append(row)
        result = {"schema_version": "production-media-v1", "observed_at": datetime.now(UTC).isoformat(),
                  "records": records, "prior_attempts": prior_attempts,
                  "summary": {"planned": len(records), "downloaded": sum(r["status"] == "downloaded" for r in records),
                              "failed": sum(r["status"] == "failed" for r in records),
                              "skipped": sum(r["status"] == "skipped" for r in records),
                              "bytes": sum(r.get("bytes", 0) for r in records),
                              "transferred_bytes": usage(), "uncertain_bytes": sum(r["uncertain_bytes"] for r in budget["plans"].values()),
                              "cumulative_byte_bound": cumulative_byte_bound,
                              "pending_plans": len(pending), "deadline_reached": time.monotonic() >= deadline},
                  "transfer_budget": {"path": str(budget_path), "sha256": file_hash(budget_path)}}
        atomic_write(output / "index.json", canonical(result) + b"\n")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-index", type=Path)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--deadline-seconds", type=float, default=1200)
    args = parser.parse_args()
    result = retain_many(
        args.plan, args.output, base_index=args.base_index, workers=args.workers, deadline_seconds=args.deadline_seconds)
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
