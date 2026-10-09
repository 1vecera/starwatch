"""Source-bound classification packets and independent-review promotion gates."""
from __future__ import annotations

import os
import argparse
import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

VERSION = "production-labels-v1"
TOPICS = frozenset({
    "housing", "transport", "environment", "public_space", "public_finance", "education",
    "health_social", "governance", "safety", "culture_sport", "economy_work", "election_process", "other",
})
CRITICAL = frozenset({"wrong_owner", "unsupported_speaker", "unsupported_quote", "wrong_identity"})
NATIVE_SOURCE = "native:collaboration"
OUTPUT_KINDS = {"classification": "labels", "independent_review": "review"}


def digest(value: object) -> str:
    """Hash a canonical JSON value so independent reviews bind to exact labels."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    """Replace a local artifact only after complete JSON serialization."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def cached_cards(project: Path) -> list[dict]:
    """Reuse independently owned cached publications without promoting speakers."""
    reviews = [json.loads((project / "data/evidence" / name).read_text()) for name in (
        "top10_profile_review.json", "top10_organization_profile_review.json")]
    profiles = {p["handle"]: p for review in reviews for p in review["profiles"]}
    posts = json.loads((project / "data/evidence/top10_unique_posts.json").read_text())["posts"]
    cards = []
    for post in posts:
        if post["owner_conflict"] or len(post["direct_entity_keys"]) != 1:
            continue
        owner = post["direct_entity_keys"][0]
        observations = [o for o in post["observations"] if o["entity_key"] == owner
                        and o["publication_relation"] == "observed_profile_is_owner"]
        if not observations:
            continue
        observation = max(observations, key=lambda o: o["fetched_at"])
        text = observation["text"] or ""
        profile = profiles[observation["handle"]]
        cards.append({"asset_id": post["post_id"], "entity_id": owner, "city": profile["city"],
                      "entity_kind": profile["entity_kind"], "source_url": observation["url"],
                      "published_at": observation["published_at"], "observed_at": observation["fetched_at"],
                      "platform": "instagram", "asset_type": observation["kind"], "text": text,
                      "content_sha256": text_digest(text), "owner_status": "independently_confirmed",
                      "speaker_entity_id": None, "speaker_status": "unknown",
                      "provenance": "data/evidence/top10_unique_posts.json"})
    return sorted(cards, key=lambda x: (x["city"], x["asset_type"] or "", x["asset_id"]))


def string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_labels(cards: list[dict], submission: object) -> dict:
    """Reject malformed packets and unsupported attribution without partially admitting them."""
    errors = []
    expected = {c["asset_id"]: c for c in cards}
    if len(expected) != len(cards):
        raise ValueError("Packet has duplicate asset IDs")
    if not isinstance(submission, dict):
        return {"valid": False, "items": 0, "errors": [{"error": "submission_must_be_object"}]}
    if (submission.get("schema_version") != VERSION or not submission.get("assignment_id")
            or not submission.get("session_id") or not isinstance(submission.get("items"), list)):
        errors.append({"asset_id": None, "error": "invalid_submission_header"})
    items = submission.get("items") if isinstance(submission.get("items"), list) else []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            errors.append({"asset_id": None, "error": "item_must_be_object"})
            continue
        asset = item.get("asset_id")
        if not isinstance(asset, str) or asset not in expected or asset in seen:
            errors.append({"asset_id": None, "error": "unexpected_or_duplicate_asset"})
            continue
        seen.add(asset)
        card = expected[asset]
        if set(item) - {"asset_id", "content_sha256", "topics", "claims", "abstain_reason", "coverage"}:
            errors.append({"asset_id": asset, "error": "unknown_label_fields"})
        if item.get("content_sha256") != card["content_sha256"]:
            errors.append({"asset_id": asset, "error": "stale_content"})
        if card["owner_status"] != "independently_confirmed":
            errors.append({"asset_id": asset, "error": "wrong_owner"})
        topics = item.get("topics")
        if not string_list(topics) or len(topics) != len(set(topics)) or set(topics) - TOPICS:
            errors.append({"asset_id": asset, "error": "invalid_topics"})
        limit = card.get("claim_limit", 3)
        coverage = item.get("coverage")
        coverage_valid = isinstance(coverage, dict)
        if coverage_valid:
            truncated, omitted = coverage.get("claims_truncated"), coverage.get("omitted_claims_count")
            coverage_valid = (type(coverage.get("claim_limit")) is int and coverage.get("claim_limit") == limit
                and coverage.get("basis") == card.get("coverage_basis", "supplied_caption_only")
                and type(truncated) is bool and isinstance(coverage.get("note"), str)
                and bool(coverage["note"].strip()) and "omitted_claims_count" in coverage
                and ((truncated and (omitted is None or (type(omitted) is int and omitted > 0)))
                     or (not truncated and type(omitted) is int and omitted == 0)))
        if not coverage_valid:
            errors.append({"asset_id": asset, "error": "invalid_or_missing_coverage"})
        claims = item.get("claims")
        if not isinstance(claims, list) or len(claims) > limit:
            errors.append({"asset_id": asset, "error": "invalid_claims_or_packet_limit"})
            continue
        seen_spans = set()
        for index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                errors.append({"asset_id": asset, "claim_index": index, "error": "claim_must_be_object"})
                continue
            if set(claim) - {"text", "start", "end", "topics", "claim_type", "speaker_entity_id", "speaker_status"}:
                errors.append({"asset_id": asset, "claim_index": index, "error": "unknown_claim_fields"})
            start, end, quote = claim.get("start"), claim.get("end"), claim.get("text")
            if (type(start) is not int or type(end) is not int or not isinstance(quote, str)
                    or not 0 <= start < end <= len(card["text"]) or card["text"][start:end] != quote
                    or not quote.strip()):
                errors.append({"asset_id": asset, "claim_index": index, "error": "unsupported_quote"})
            elif (start, end) in seen_spans:
                errors.append({"asset_id": asset, "claim_index": index, "error": "duplicate_claim_span"})
            else:
                seen_spans.add((start, end))
            if ("speaker_entity_id" not in claim or claim["speaker_entity_id"] is not None
                    or claim.get("speaker_status") != "unknown"):
                errors.append({"asset_id": asset, "claim_index": index, "error": "unsupported_speaker"})
            if claim.get("claim_type") != "source_statement":
                errors.append({"asset_id": asset, "claim_index": index, "error": "unsupported_claim_type"})
            if (not string_list(claim.get("topics")) or not claim["topics"]
                    or len(claim["topics"]) != len(set(claim["topics"])) or set(claim["topics"]) - TOPICS):
                errors.append({"asset_id": asset, "claim_index": index, "error": "invalid_claim_topics"})
        if not topics and not (isinstance(item.get("abstain_reason"), str) and item["abstain_reason"].strip()):
            errors.append({"asset_id": asset, "error": "missing_abstention_reason"})
    errors.extend({"asset_id": asset, "error": "missing_asset"} for asset in sorted(set(expected) - seen))
    return {"schema_version": VERSION, "valid": not errors, "items": len(seen), "errors": errors,
            "submission_sha256": digest(submission)}


def _assignment(document: dict, registry: dict) -> dict | None:
    if not isinstance(document, dict) or not isinstance(registry, dict):
        return None
    assignments = registry.get("assignments")
    if not isinstance(assignments, list) or not all(isinstance(row, dict) for row in assignments):
        return None
    assignment_id = document.get("assignment_id")
    if not isinstance(assignment_id, str) or not assignment_id:
        return None
    rows = [row for row in assignments if row.get("assignment_id") == assignment_id]
    if len(rows) != 1:
        return None
    return rows[0]


def _canonical_path(value: object) -> Path | None:
    """Native paths cannot be relative, aliases, traversal paths or symlink escapes."""
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute() or str(path) != value or str(path.resolve()) != value:
        return None
    return path


def _sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _native_parent_context(row: dict, registry: dict) -> tuple[object, object]:
    """Resolve a resumed sibling from its pinned original coordinator registration."""
    default = registry.get("native_parent_task_path"), registry.get("native_parent_session_id")
    if row.get("parent_session_id") == default[1]:
        return default
    references = registry.get("native_parent_registries")
    if not isinstance(references, list):
        return None, None
    matches = []
    for reference in references:
        if not isinstance(reference, dict):
            return None, None
        path = _canonical_path(reference.get("path"))
        if path is None or not _sha256(reference.get("sha256")):
            return None, None
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
                return None, None
            source = json.loads(raw)
        except (OSError, ValueError, TypeError):
            return None, None
        assignments = source.get("assignments") if isinstance(source, dict) else None
        if not isinstance(assignments, list):
            return None, None
        original = [value for value in assignments if isinstance(value, dict)
                    and value.get("assignment_id") == row.get("assignment_id")]
        if len(original) == 1 and original[0] == row:
            matches.append((source.get("native_parent_task_path"), source.get("native_parent_session_id")))
    return matches[0] if len(matches) == 1 else (None, None)


def validate_assignment_provenance(assignment: dict, registry: dict) -> bool:
    """Validate native coordinator receipts; historical Herdr uses its unchanged gate.

    The registry is coordinator-owned trusted input. A worker cannot register itself.
    Native task names are the actual canonical names returned by spawn_agent, and
    are never represented as Herdr pane identities or fabricated Herdr sessions.
    """
    try:
        row = _assignment(assignment, registry)
        if row is None or row != assignment or row.get("binding_error"):
            return False
        binding = row.get("session_binding")
        receipt = row.get("spawn_receipt")
        if not isinstance(binding, dict) or not isinstance(receipt, dict):
            return False
        if binding.get("source") != NATIVE_SOURCE:
            return False
        parent, parent_session = _native_parent_context(row, registry)
        task = row.get("task_path")
        if (not isinstance(parent, str) or not re.fullmatch(r"/root(?:/[a-z0-9_]+)*", parent)
                or not isinstance(parent_session, str) or not parent_session
                or not isinstance(task, str)
                or not re.fullmatch(re.escape(parent) + r"/[a-z0-9_]+", task)):
            return False
        if (row.get("parent_session_id") != parent_session
                or binding.get("parent_session_id") != parent_session
                or binding.get("task_path") != task or receipt.get("task_name") != task
                or row.get("session_id") != "native:" + task
                or row.get("pane") or row.get("prompt_receipt") or row.get("start_receipt")):
            return False
        assignments = registry["assignments"]
        task_rows = [other for other in assignments if other.get("task_path") == task]
        if len(task_rows) != 1:
            # Explicitly registered packet reviews can share one real resumed task.
            # Classifier/reviewer reuse and invented descendant identities stay invalid.
            reuse = registry.get("native_repeated_review_tasks")
            allowed = reuse.get(task) if isinstance(reuse, dict) else None
            ids = [other.get("assignment_id") for other in task_rows]
            if (not isinstance(allowed, list) or not all(isinstance(value, str) for value in allowed)
                    or not all(isinstance(value, str) for value in ids)
                    or len(set(ids)) != len(ids) or sorted(allowed) != sorted(ids)
                    or len(set(allowed)) != len(allowed)
                    or any(other.get("task_kind") != "independent_review"
                           or other.get("output_kind") != "review"
                           or other.get("session_id") != row.get("session_id")
                           or other.get("parent_session_id") != parent_session
                           or _native_parent_context(other, registry) != (parent, parent_session)
                           or other.get("spawn_receipt") != receipt
                           or other.get("session_binding") != binding
                           for other in task_rows)):
                return False
        kind = OUTPUT_KINDS.get(row.get("task_kind"))
        if kind is None or row.get("output_kind") != kind:
            return False
        brief = _canonical_path(row.get("brief"))
        cards = _canonical_path(row.get("cards_path"))
        directory = _canonical_path(row.get("output_directory"))
        output = _canonical_path(row.get("output_path"))
        if (brief is None or cards is None or directory is None or output is None
                or not directory.is_dir() or not brief.is_file() or not output.is_file()
                or not cards.is_file()
                or brief.parent != directory or output.parent != directory
                or (row["task_kind"] == "classification" and cards.parent != directory)
                or output.name != kind + ".json"
                or sum(other.get("output_directory") == str(directory) for other in assignments) != 1
                or sum(other.get("output_path") == str(output) for other in assignments) != 1
                or not _sha256(row.get("brief_sha256")) or not _sha256(row.get("cards_sha256"))
                or hashlib.sha256(brief.read_bytes()).hexdigest() != row["brief_sha256"]
                or hashlib.sha256(cards.read_bytes()).hexdigest() != row["cards_sha256"]):
            return False
        registered = datetime.fromisoformat(row["registered_at"])
        if registered.tzinfo is None or registered.timestamp() > output.stat().st_mtime:
            return False
        if row["task_kind"] == "independent_review" and not _sha256(row.get("submission_sha256")):
            return False
        return True
    except (KeyError, TypeError, ValueError, OSError, OverflowError):
        return False


def assignment_binding(document: dict, registry: dict, task_kind: str) -> bool:
    """Trust exact coordinator-observed native or legacy Herdr receipts."""
    row = _assignment(document, registry)
    if row is None:
        return False
    binding = row.get("session_binding", {})
    if not isinstance(binding, dict):
        return False
    if binding.get("source") == NATIVE_SOURCE:
        if (not validate_assignment_provenance(row, registry)
                or row.get("session_id") != document.get("session_id")
                or row.get("task_kind") != task_kind
                or (task_kind == "independent_review"
                    and row["submission_sha256"] != document.get("submission_sha256"))):
            return False
        try:
            return digest(json.loads(Path(row["output_path"]).read_text())) == digest(document)
        except (OSError, ValueError, TypeError):
            return False
    observed = binding.get("agent_receipt", {})
    receipt = row.get("prompt_receipt", {})
    if not isinstance(observed, dict) or not isinstance(receipt, dict):
        return False
    receipt = receipt.get("result", receipt)
    if not isinstance(receipt, dict):
        return False
    prompt = receipt.get("agent", {})
    if (not isinstance(prompt, dict) or not isinstance(prompt.get("agent_session", {}), dict)
            or not isinstance(observed.get("agent_session", {}), dict)):
        return False
    prompt_session = prompt.get("agent_session", {}).get("value")
    return bool(row.get("pane") and row.get("session_id")
                and row["session_id"] == document.get("session_id")
                and row.get("task_kind") == task_kind and row.get("brief_sha256")
                and not row.get("binding_error")
                and binding.get("source") == "herdr:codex"
                and binding.get("pane") == row["pane"] == observed.get("pane_id") == prompt.get("pane_id")
                and binding.get("session_id") == row["session_id"] == observed.get("agent_session", {}).get("value")
                and observed.get("agent_session", {}).get("source") == "herdr:codex"
                and (prompt_session is None or prompt_session == row["session_id"]))


def reviewed_records(cards: list[dict], submission: object, review: object, registry: dict) -> dict:
    """Promote exact independent verdicts; complete malformed/critical batches stay held."""
    validation = validate_labels(cards, submission)
    reasons = list(validation["errors"])
    submission = submission if isinstance(submission, dict) else {}
    review = review if isinstance(review, dict) else {}
    if not assignment_binding(submission, registry, "classification"):
        reasons.append({"asset_id": None, "error": "classifier_not_bound_to_registry"})
    if not assignment_binding(review, registry, "independent_review"):
        reasons.append({"asset_id": None, "error": "reviewer_not_bound_to_registry"})
    for document in (submission, review):
        row = _assignment(document, registry)
        if row and isinstance(row.get("session_binding"), dict) and row["session_binding"].get("source") == NATIVE_SOURCE:
            try:
                matches = digest(json.loads(Path(row["cards_path"]).read_text())) == digest(cards)
            except (KeyError, TypeError, ValueError, OSError):
                matches = False
            if not matches:
                reasons.append({"asset_id": None, "error": "native_source_packet_mismatch"})
    if (not review.get("assignment_id") or review["assignment_id"] == submission.get("assignment_id")
            or not review.get("session_id") or review["session_id"] == submission.get("session_id")):
        reasons.append({"asset_id": None, "error": "review_not_independent"})
    if review.get("schema_version") != VERSION or review.get("submission_sha256") != digest(submission):
        reasons.append({"asset_id": None, "error": "review_not_bound_to_submission"})
    review_items = review.get("items")
    if not isinstance(review_items, list):
        reasons.append({"asset_id": None, "error": "review_items_must_be_array"})
        review_items = []
    reviews, assets = {}, {c["asset_id"] for c in cards}
    for item in review_items:
        if not isinstance(item, dict):
            reasons.append({"asset_id": None, "error": "review_item_must_be_object"})
            continue
        asset = item.get("asset_id")
        if not isinstance(asset, str) or asset in reviews or asset not in assets:
            reasons.append({"asset_id": None, "error": "duplicate_or_unexpected_review"})
            continue
        complete = (isinstance(item.get("decision"), str) and item["decision"] in {"accept", "reject", "revise"}
            and string_list(item.get("critical_errors")) and string_list(item.get("topic_errors"))
            and isinstance(item.get("reason"), str) and bool(item["reason"].strip())
            and isinstance(item.get("reviewed_claim_indexes"), list)
            and all(type(i) is int for i in item["reviewed_claim_indexes"]))
        if not complete:
            reasons.append({"asset_id": asset, "error": "incomplete_reviewer_verdict"})
            continue
        reviews[asset] = item
        if item["critical_errors"]:
            reasons.append({"asset_id": asset, "error": "critical_review_failure", "details": item["critical_errors"]})
    hold = bool(reasons)
    admitted, quarantine = [], []
    items = submission.get("items") if isinstance(submission.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("asset_id"), str):
            quarantine.append({"label": item, "reason": "malformed_label"})
            continue
        verdict = reviews.get(item["asset_id"])
        claims = item.get("claims") if isinstance(item.get("claims"), list) else []
        fully_reviewed = verdict and sorted(verdict["reviewed_claim_indexes"]) == list(range(len(claims)))
        if (hold or not verdict or not fully_reviewed or verdict["decision"] != "accept" or verdict["topic_errors"]):
            quarantine.append({"label": item, "review": verdict, "reason": "batch_hold" if hold
                               else "unreviewed_or_rejected"})
        else:
            admitted.append({**item, "classification_assignment": submission["assignment_id"],
                             "review_assignment": review["assignment_id"], "review_session_id": review["session_id"],
                             "label_sha256": digest(item), "review_status": "independently_reviewed"})
    return {"schema_version": VERSION, "batch_hold": hold, "errors": reasons,
            "verified": admitted, "quarantine": quarantine,
            "counts": {"classified": len(items), "verified": len(admitted), "quarantined": len(quarantine),
                       "reviewed": len(reviews)}}


def registered_output(path: Path, registry: dict, task_kind: str) -> dict:
    """Load only the isolated output path assigned by the coordinator's registry."""
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or not assignment_binding(document, registry, task_kind):
        raise ValueError("Output does not match a recorded native assignment/session")
    row = next(r for r in registry["assignments"] if r["assignment_id"] == document["assignment_id"])
    if hashlib.sha256(Path(row["brief"]).read_bytes()).hexdigest() != row["brief_sha256"]:
        raise ValueError("Assignment brief changed after registration")
    if row["session_binding"].get("source") == NATIVE_SOURCE:
        if _canonical_path(str(path.absolute())) != Path(row["output_path"]):
            raise ValueError("Output path differs from its exact registered native output")
    elif path.resolve().parent != Path(row["brief"]).resolve().parent:
        raise ValueError("Output path is outside its registered worker directory")
    return document


def freeze_classification_bundle(legacy_registry: Path, native_registry: Path,
                                 batches: list[dict], output_directory: Path) -> dict:
    """Write a new frozen bundle; never alter input registries, workers or the lake.

    Original registered paths stay intact. Exact input bytes are retained as audit
    snapshots, and bundle hashes let importers reject changed live input files.
    Only the coordinator should call this helper on its own new output directory.
    The native registry input is an immutable filtered snapshot containing only
    completed classification/review rows linked to these packets; preparation or
    identity-work rows intentionally fail this classification-specific gate.
    """
    inputs: dict[Path, bytes] = {}

    def read(path: Path) -> bytes:
        path = path.resolve()
        if path not in inputs:
            inputs[path] = path.read_bytes()
        return inputs[path]

    legacy = json.loads(read(legacy_registry))
    native = json.loads(read(native_registry))
    if (not isinstance(legacy, dict) or not isinstance(native, dict)
            or not isinstance(legacy.get("assignments"), list)
            or not isinstance(native.get("assignments"), list)
            or not all(isinstance(row, dict) for row in legacy["assignments"] + native["assignments"])):
        raise ValueError("Registries must contain assignment objects")
    combined = copy.deepcopy(legacy)
    combined["assignments"].extend(copy.deepcopy(native["assignments"]))
    for key in ("native_parent_session_id", "native_parent_task_path"):
        if key not in native or (key in combined and combined[key] != native[key]):
            raise ValueError("Native coordinator identity missing or conflicts")
        combined[key] = native[key]
    ids = [row.get("assignment_id") for row in combined["assignments"]]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Combined registry assignment IDs must be unique")
    for row in native["assignments"]:
        if not validate_assignment_provenance(row, combined):
            raise ValueError("Native assignment provenance is invalid")
        read(Path(row["brief"]))
        read(Path(row["cards_path"]))
        read(Path(row["output_path"]))
    frozen_batches = []
    results = []
    for batch in batches:
        metadata = {}
        if "packet_id" in batch:
            if not isinstance(batch["packet_id"], str) or not batch["packet_id"].strip():
                raise ValueError("Packet ID must be a nonempty string")
            metadata["packet_id"] = batch["packet_id"]
        if "supersedes" in batch:
            supersedes = batch["supersedes"]
            if (not isinstance(supersedes, dict)
                    or any(not isinstance(asset, str) or not asset or not _sha256(label_hash)
                           for asset, label_hash in supersedes.items())):
                raise ValueError("Supersession requires exact asset IDs and label hashes")
            metadata["supersedes"] = copy.deepcopy(supersedes)
        paths = {key: Path(batch[key]).resolve() for key in ("cards", "labels", "review")}
        raw = {key: read(path) for key, path in paths.items()}
        cards = json.loads(raw["cards"])
        labels = registered_output(paths["labels"], combined, "classification")
        review = registered_output(paths["review"], combined, "independent_review")
        classifier = _assignment(labels, combined)
        if paths["cards"].parent != Path(classifier["brief"]).resolve().parent:
            raise ValueError("Source packet is outside its registered classifier directory")
        cards_hash = hashlib.sha256(raw["cards"]).hexdigest()
        for document in (labels, review):
            row = _assignment(document, combined)
            read(Path(row["brief"]))
            if row.get("cards_sha256") != cards_hash:
                raise ValueError("Source packet differs from registered input")
            if row.get("session_binding", {}).get("source") == NATIVE_SOURCE and Path(row["cards_path"]) != paths["cards"]:
                raise ValueError("Source packet path differs from registered input")
        result = reviewed_records(cards, labels, review, combined)
        if result["batch_hold"]:
            raise ValueError("Classification batch is held by independent review")
        results.append(result)
        frozen_batches.append({**metadata, **{key: str(path) for key, path in paths.items()},
                               **{key + "_sha256": hashlib.sha256(value).hexdigest()
                                  for key, value in raw.items()}})
    if any(path.read_bytes() != raw for path, raw in inputs.items()):
        raise ValueError("Input changed while freezing classification bundle")
    output_directory = output_directory.absolute()
    if _canonical_path(str(output_directory)) is None or output_directory.exists():
        raise ValueError("Frozen bundle requires a new canonical output directory")
    if any(path.is_relative_to(output_directory) for path in inputs):
        raise ValueError("Frozen output must not contain mutable inputs")
    output_directory.mkdir(parents=True)
    registry_path = output_directory / "registry.json"
    atomic_json(registry_path, combined)
    registry_hash = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    for index, batch in enumerate(frozen_batches):
        batch.update(registry=str(registry_path), registry_sha256=registry_hash)
        snapshots = output_directory / "snapshots" / str(index)
        snapshots.mkdir(parents=True)
        batch["snapshots"] = {}
        for key in ("cards", "labels", "review"):
            target = snapshots / (key + ".json")
            target.write_bytes(inputs[Path(batch[key])])
            batch["snapshots"][key] = str(target)
        atomic_json(snapshots / "reviewed.json", results[index])
    bundle = {"schema_version": "production-label-bundle-v1", "packets": frozen_batches,
              "source_registries": [{"path": str(path.resolve()),
                 "sha256": hashlib.sha256(inputs[path.resolve()]).hexdigest()}
                 for path in (legacy_registry, native_registry)]}
    atomic_json(output_directory / "bundle.json", bundle)
    atomic_json(output_directory / "manifest.json", {
        "schema_version": "production-classification-freeze-v1",
        "registry_sha256": registry_hash,
        "bundle_sha256": hashlib.sha256((output_directory / "bundle.json").read_bytes()).hexdigest(),
        "inputs": [{"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
                   for path, raw in sorted(inputs.items())]})
    return {"registry": str(registry_path), "bundle": str(output_directory / "bundle.json"),
            "manifest": str(output_directory / "manifest.json"),
            "batches": len(frozen_batches), "verified": sum(r["counts"]["verified"] for r in results)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["cached-cards", "validate", "review"])
    parser.add_argument("--project", type=Path, default=Path(os.environ.get("CZLAKE_PROJECT") or Path(__file__).resolve().parents[3]))
    parser.add_argument("--cards", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "cached-cards":
        result = cached_cards(args.project)
    else:
        cards = json.loads(args.cards.read_text())
        if args.command == "validate":
            result = validate_labels(cards, json.loads(args.labels.read_text()))
        else:
            registry = json.loads(args.registry.read_text())
            labels = registered_output(args.labels, registry, "classification")
            review = registered_output(args.review, registry, "independent_review")
            assignment = next(r for r in registry["assignments"] if r["assignment_id"] == labels["assignment_id"])
            if assignment.get("cards_sha256") != hashlib.sha256(args.cards.read_bytes()).hexdigest():
                raise ValueError("Source packet differs from the coordinator's registered input")
            result = reviewed_records(cards, labels, review, registry)
    atomic_json(args.output, result)
    print(json.dumps({"output": str(args.output), "records": len(result)}))


if __name__ == "__main__":
    main()
