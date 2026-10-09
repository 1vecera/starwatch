"""Restartable capped Apify collection with reviewed input and public-metadata policies.

No request is retried. A persisted start boundary is irreversible without binding
an existing, independently matched run. Source replies never reach disk unfiltered.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .production_budget import (
    CITIES,
    SCOPE_ID,
    TERMINAL,
    AmbiguousStart,
    BudgetError,
    ProductionBudget,
    canonical,
    digest,
    file_hash,
    money,
    timestamp,
)

from .production_new_platforms import NEW_ACTORS, PRICE_UNITS, TIKTOK, X, new_metadata, validate_new_input

API = "https://api.apify.com/v2"
POLICY_VERSION = "public-metadata-v1"
ACTORS = {
    "apify/instagram-profile-scraper",
    "apify/instagram-scraper",
    "apify/facebook-posts-scraper",
    "apify/google-search-scraper",
}
ACTORS |= NEW_ACTORS
GOOGLE_DISABLED = {
    "aiOverview": {"scrapeFullAiOverview": False},
    "aiModeSearch": {"enableAiMode": False},
    "geminiSearch": {"enableGemini": False},
    "perplexitySearch": {"enablePerplexity": False, "returnImages": False, "returnRelatedQuestions": False},
    "chatGptSearch": {"enableChatGpt": False},
    "copilotSearch": {"enableCopilot": False},
    "maximumLeadsEnrichmentRecords": 0,
    "verifyLeadsEnrichmentEmails": False,
    "linkProspecting": {"brandName": ""},
    "websiteContentScraper": {"enable": False},
    "focusOnPaidAds": False,
    "saveHtml": False,
    "saveHtmlToKeyValueStore": False,
    "includeIcons": False,
}


class TransportFailure(BudgetError):
    """Provider failure with a small sanitized diagnostic; raw response text is never persisted."""

    def __init__(self, diagnostic: dict):
        super().__init__("Provider request failed; inspect the sanitized ledger diagnostic")
        self.diagnostic = diagnostic


class Transport(Protocol):
    def start(self, actor: str, run_input: dict, caps: dict) -> dict: ...
    def get_run(self, run_id: str) -> dict: ...
    def get_input(self, store_id: str) -> dict: ...
    def dataset_page(self, dataset_id: str, offset: int, limit: int) -> list[dict]: ...


class ApifyTransport:
    """One attempt per HTTP call, bounded response sizes, no token in URLs or exception output."""

    def __init__(self, token: str, *, request_timeout_s: int = 30):
        if not token:
            raise ValueError("APIFY_TOKEN is required for network commands")
        self.token = token
        self.request_timeout_s = request_timeout_s

    def _request(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None):
        url = API + path + ("?" + urlencode(params) if params else "")
        request = Request(
            url,
            data=canonical(body) if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.request_timeout_s) as response:
                payload = response.read(16 * 1024 * 1024 + 1)
        except HTTPError as exc:
            diagnostic = {
                "kind": "http_error",
                "operation": "start" if method == "POST" else "read",
                "http_status": exc.code,
            }
            # Known provider error codes only: never retain a response message/body or arbitrary type string.
            known_types = {
                "invalid-input",
                "invalid-request",
                "invalid-request-body",
                "invalid-value",
                "actor-not-found",
                "not-found",
                "unauthorized",
                "insufficient-permissions",
                "not-enough-credit",
                "rate-limit-exceeded",
                "actor-is-not-rented",
                "max-total-charge-usd-too-low",
            }
            try:
                error_type = json.loads(exc.read(32768)).get("error", {}).get("type")
                if error_type in known_types:
                    diagnostic["error_type"] = error_type
            except (ValueError, UnicodeError, TypeError, AttributeError, OSError):
                pass
            raise TransportFailure(diagnostic) from None
        except (URLError, TimeoutError, OSError):
            raise TransportFailure(
                {"kind": "transport_error", "operation": "start" if method == "POST" else "read"}
            ) from None
        if len(payload) > 16 * 1024 * 1024:
            raise BudgetError("Apify response exceeded the in-memory byte limit")
        try:
            return json.loads(payload, parse_float=Decimal)
        except (ValueError, UnicodeError):
            raise BudgetError("Apify returned malformed JSON") from None

    def start(self, actor: str, run_input: dict, caps: dict) -> dict:
        return self._request("POST", f"/acts/{actor.replace('/', '~')}/runs", params=caps, body=run_input)["data"]

    def get_run(self, run_id: str) -> dict:
        return self._request("GET", f"/actor-runs/{run_id}")["data"]

    def get_input(self, store_id: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", store_id):
            raise ValueError("Invalid key-value store ID")
        return self._request("GET", f"/key-value-stores/{store_id}/records/INPUT")

    def dataset_page(self, dataset_id: str, offset: int, limit: int) -> list[dict]:
        return self._request(
            "GET",
            f"/datasets/{dataset_id}/items",
            params={"offset": offset, "limit": limit, "clean": "true", "format": "json"},
        )


def bounded_int(value, lower: int, upper: int, name: str) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer between {lower} and {upper}")
    return value


def public_url(value: str, hosts: set[str]) -> None:
    if not isinstance(value, str):
        raise TypeError("An exact HTTPS URL is required")
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.hostname not in hosts
        or url.username
        or url.password
        or url.port is not None
        or url.query
        or url.fragment
        or len(value) > 2048
    ):
        raise ValueError("Only exact public platform HTTPS URLs without query/credentials are allowed")
    if not re.fullmatch(r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?/?", url.path):
        raise ValueError("Unsupported public platform URL path")
    if url.path.split("/")[1].lower() in {"groups", "stories", "accounts", "explore", "direct", "profile.php"}:
        raise ValueError("Unsupported source lane")


def validate_input(actor: str, run_input: dict, max_items: int) -> None:
    """Allow reviewed input fields only and explicitly disable every metered extra."""
    if actor not in ACTORS or not isinstance(run_input, dict):
        raise ValueError("Unknown actor or invalid input")
    if actor in NEW_ACTORS:
        validate_new_input(actor, run_input, max_items, bounded_int)
        return
    if actor == "apify/instagram-profile-scraper":
        allowed = {"usernames", "includeAboutSection"}
        if run_input.get("includeAboutSection") is not False:
            raise ValueError("About-section enrichment must be explicitly false")
        names = run_input["usernames"]
        if (
            not isinstance(names, list)
            or not 1 <= len(names) <= max_items
            or any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", n) for n in names)
        ):
            raise ValueError("Invalid or uncapped profile handles")
    elif actor == "apify/instagram-scraper":
        allowed = {"resultsType", "directUrls", "resultsLimit", "onlyPostsNewerThan", "addParentData"}
        if run_input.get("resultsType") not in {"posts", "reels"} or run_input.get("addParentData") is not False:
            raise ValueError("Only posts/reels with parent enrichment disabled are allowed")
        urls = run_input["directUrls"]
        if not isinstance(urls, list) or not 1 <= len(urls) <= max_items:
            raise ValueError("An exact bounded URL list is required")
        for url in urls:
            public_url(url, {"instagram.com", "www.instagram.com"})
        bounded_int(run_input["resultsLimit"], 1, max_items, "resultsLimit")
    elif actor == "apify/facebook-posts-scraper":
        allowed = {"startUrls", "resultsLimit", "captionText", "onlyPostsNewerThan", "onlyPostsOlderThan"}
        if type(run_input.get("captionText")) is not bool:
            raise ValueError("Caption retrieval must be an explicit boolean")
        urls = run_input["startUrls"]
        if not isinstance(urls, list) or not 1 <= len(urls) <= max_items:
            raise ValueError("An exact bounded page URL list is required")
        for item in urls:
            if not isinstance(item, dict) or set(item) != {"url"}:
                raise ValueError("Only startUrls.url is allowed")
            public_url(item["url"], {"facebook.com", "www.facebook.com"})
        bounded_int(run_input["resultsLimit"], 1, max_items, "resultsLimit")
    else:
        allowed = {
            "queries",
            "maxPagesPerQuery",
            "countryCode",
            "searchLanguage",
            "languageCode",
            "site",
            "quickDateRange",
            "beforeDate",
            "afterDate",
            "mobileResults",
            "includeUnfilteredResults",
            "forceExactMatch",
            *GOOGLE_DISABLED,
        }
        for key, disabled in GOOGLE_DISABLED.items():
            if key not in run_input or canonical(run_input[key]) != canonical(disabled):
                raise ValueError(f"Search add-on {key} must be explicitly disabled")
        queries = run_input["queries"]
        if not isinstance(queries, str) or not queries.strip() or len(queries) > 100000:
            raise ValueError("Exact bounded search queries are required")
        pages = bounded_int(run_input["maxPagesPerQuery"], 1, 10, "maxPagesPerQuery")
        if len(queries.strip().splitlines()) * pages > max_items:
            raise ValueError("Search page count exceeds maxItems")
        for key in {"mobileResults", "includeUnfilteredResults", "forceExactMatch"} & run_input.keys():
            if type(run_input[key]) is not bool:
                raise ValueError("Invalid search boolean")
    if set(run_input) - allowed:
        raise ValueError("Unreviewed input fields are forbidden")
    for key in {
        "onlyPostsNewerThan",
        "onlyPostsOlderThan",
        "countryCode",
        "searchLanguage",
        "languageCode",
        "site",
        "quickDateRange",
        "beforeDate",
        "afterDate",
    } & run_input.keys():
        if not isinstance(run_input[key], str) or not 1 <= len(run_input[key]) <= 250:
            raise ValueError("Invalid search/date input string")


def validate_manifest(manifest: dict, now: float, *, enforce_freshness: bool = True) -> dict:
    """Require exact inputs and a pinned, actor-matched live schema/pricing receipt."""
    required = {
        "schema_version",
        "batch_id",
        "scope_id",
        "cities",
        "actor",
        "input",
        "input_sha256",
        "purpose",
        "max_total_charge_usd",
        "max_items",
        "timeout_s",
        "memory_mb",
        "price_basis",
    }
    if set(manifest) != required or manifest["schema_version"] != 1 or manifest["scope_id"] != SCOPE_ID:
        raise ValueError("Unexpected manifest fields/version/scope")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", manifest["batch_id"]):
        raise ValueError("Unsafe idempotency batch ID")
    if (
        not isinstance(manifest["cities"], list)
        or not manifest["cities"]
        or not set(manifest["cities"]) <= CITIES
        or len(set(manifest["cities"])) != len(manifest["cities"])
    ):
        raise ValueError("Only the existing ten city names are authorized")
    if not isinstance(manifest["purpose"], str) or not 1 <= len(manifest["purpose"]) <= 500:
        raise ValueError("An exact bounded purpose is required")
    maximum = money(manifest["max_total_charge_usd"])
    if maximum <= 0 or maximum > 100:
        raise ValueError("A positive bounded maxTotalChargeUsd is mandatory")
    if enforce_freshness and manifest["actor"] == "apify/google-search-scraper" and maximum < Decimal("0.50"):
        raise ValueError("Google requires at least a $0.50 run cap, as recorded in authenticated provider pricingInfo")
    items = bounded_int(manifest["max_items"], 1, 10000, "max_items")
    bounded_int(manifest["timeout_s"], 1, 900, "timeout_s")
    memory = bounded_int(manifest["memory_mb"], 128, 4096, "memory_mb")
    if memory & (memory - 1):
        raise ValueError("Memory must be a power of two")
    validate_input(manifest["actor"], manifest["input"], items)
    if manifest["input_sha256"] != digest(manifest["input"]):
        raise ValueError("Exact input hash mismatch")
    basis = manifest["price_basis"]
    expected_keys = {
        "snapshot_path",
        "snapshot_sha256",
        "observed_at",
        "pricing_model",
        "tier",
        "unit",
        "expected_upper_usd",
        "rationale",
    }
    if not isinstance(basis, dict) or set(basis) != expected_keys:
        raise ValueError("Complete exact price basis is required")
    if money(basis["expected_upper_usd"]) > maximum or not all(basis[k] for k in expected_keys):
        raise ValueError("Price basis is incomplete or exceeds the reserved cap")
    path = Path(basis["snapshot_path"])
    if file_hash(path) != basis["snapshot_sha256"]:
        raise ValueError("Pinned live pricing/schema snapshot changed")
    snapshot = json.loads(path.read_text(), parse_float=Decimal)
    if (
        snapshot["data"]["actorInfo"]["fullName"] != manifest["actor"]
        or snapshot["observed_at"] != basis["observed_at"]
    ):
        raise ValueError("Price snapshot belongs to another actor/observation")
    age = now - timestamp(basis["observed_at"])
    if enforce_freshness and not -60 <= age <= 86400:
        raise ValueError("Live pricing/schema receipt is older than 24 hours or in the future")
    pricing = snapshot["data"]["actorInfo"]["pricing"]
    if basis["pricing_model"] != pricing["model"] or basis["tier"] != pricing["userTier"]:
        raise ValueError("Price model/tier does not match the live receipt")
    unit = {
        "apify/instagram-profile-scraper": "Profile",
        "apify/instagram-scraper": "Result",
        "apify/facebook-posts-scraper": "Post",
        "apify/google-search-scraper": "Scraped search result page",
        **PRICE_UNITS,
    }[manifest["actor"]]
    if basis["unit"] != unit or pricing["model"] != "PAY_PER_EVENT":
        raise ValueError("Unreviewed pricing model/unit")
    needed = {unit}
    if manifest["actor"] == "apify/facebook-posts-scraper":
        needed.add("Actor start")
        if {"onlyPostsNewerThan", "onlyPostsOlderThan"} & manifest["input"].keys():
            needed.add("Add-on: Date filter")
    if manifest["actor"] == TIKTOK:
        needed.add("Actor start")
    if manifest["actor"] == X:
        needed.add("Search/Profile/List etc Query")
    rates = {
        event["title"]: money(
            next(rate["priceUsd"] for rate in event["tieredPricing"] if rate["tier"] == basis["tier"])
        )
        for event in pricing["events"]
        if event["title"] in needed
    }
    conservative = rates[unit] * items
    if manifest["actor"] == "apify/google-search-scraper":
        start_event = next(event for event in pricing["events"] if event["title"] == "Actor Start")
        # The pinned description bills one start event per GB, with a minimum of one event.
        start_units = max(1, (memory + 1023) // 1024)
        conservative += money(start_event["priceUsd"]) * start_units
    if manifest["actor"] == "apify/facebook-posts-scraper":
        conservative += rates["Actor start"]
        if {"onlyPostsNewerThan", "onlyPostsOlderThan"} & manifest["input"].keys():
            conservative += rates["Add-on: Date filter"] * items
    if manifest["actor"] == TIKTOK:
        conservative += rates["Actor start"]
    if manifest["actor"] == X:
        conservative += rates["Search/Profile/List etc Query"] * len(manifest["input"]["searchTerms"])
    if enforce_freshness and money(basis["expected_upper_usd"]) < conservative:
        raise ValueError("Price basis understates the capped item/start/add-on upper estimate")
    properties = snapshot["data"]["inputSchema"]["properties"]
    if not manifest["input"].keys() <= properties.keys():
        raise ValueError("Input fields are absent from the pinned live schema")
    return {"actor_id": snapshot["data"]["actorInfo"]["id"], "manifest": json.loads(canonical(manifest))}


# Scalar fields cannot smuggle a nested identity object. Nested/list fields need their own schema.
POST = {
    "id",
    "shortCode",
    "type",
    "productType",
    "url",
    "timestamp",
    "caption",
    "alt",
    "ownerId",
    "ownerUsername",
    "ownerFullName",
    "displayUrl",
    "videoUrl",
    "videoViewCount",
    "videoPlayCount",
    "likesCount",
    "commentsCount",
    "dimensionsHeight",
    "dimensionsWidth",
    "isCommentsDisabled",
    "videoDuration",
}
PROFILE = {
    "id",
    "fbid",
    "username",
    "fullName",
    "biography",
    "url",
    "inputUrl",
    "externalUrl",
    "followersCount",
    "followsCount",
    "postsCount",
    "profilePicUrl",
    "profilePicUrlHD",
    "verified",
    "private",
    "isBusinessAccount",
    "businessCategoryName",
    "highlightReelCount",
    "igtvVideoCount",
}
FB_POST = {
    "id",
    "postId",
    "url",
    "postUrl",
    "facebookUrl",
    "pageId",
    "pageName",
    "userId",
    "username",
    "text",
    "time",
    "timestamp",
    "likes",
    "comments",
    "shares",
    "views",
    "videoViews",
    "isVideo",
    "isLiveVideo",
    "thumbnailUrl",
    "videoUrl",
    "imageUrl",
    "topLevelUrl",
    "inputUrl",
    "isSponsored",
    "isShare",
}
OWNER = {"id", "name", "username", "fullName", "profileUrl", "url", "profilePic", "profilePicUrl", "verified"}
MEDIA = {
    "id",
    "type",
    "__typename",
    "url",
    "thumbnail",
    "thumbnailUrl",
    "imageUrl",
    "videoUrl",
    "width",
    "height",
    "isVideo",
    "playable_url",
    "playable_url_quality_hd",
}
SEARCH = {"url", "title", "description", "snippet", "position", "displayedUrl", "date"}


def scalar_fields(item: dict, allowed: set[str]) -> dict:
    result = {}
    for key in allowed & item.keys():
        value = item[key]
        numeric = {
            "likes",
            "comments",
            "shares",
            "views",
            "videoViews",
            "videoDuration",
            "resultsTotal",
            "searchTime",
            "position",
            "width",
            "height",
            "dimensionsHeight",
            "dimensionsWidth",
        }
        if key.endswith("Count") or key in numeric:
            if type(value) in {int, float, Decimal}:
                number = float(value)
                if math.isfinite(number):
                    result[key] = value if type(value) is int else number
            elif value is None:
                result[key] = None
            continue
        if value is None or type(value) in {bool, int, str}:
            if isinstance(value, str) and len(value) > 200000:
                raise ValueError("Public metadata text exceeds field byte policy")
            result[key] = value
        elif isinstance(value, (float, Decimal)):
            number = float(value)
            if math.isfinite(number):
                result[key] = number
    return result


def object_list(item: dict, key: str, project: Callable[[dict], dict]) -> list[dict] | None:
    if key not in item:
        return None
    values = item[key]
    if not isinstance(values, list) or len(values) > 1000 or any(not isinstance(v, dict) for v in values):
        raise ValueError("Unexpected bounded public-metadata list")
    return [project(v) for v in values]


def post_metadata(item: dict, depth: int = 0) -> dict:
    if depth > 3:
        raise ValueError("Nested asset depth exceeds policy")
    result = scalar_fields(item, POST)
    for key in ("images", "hashtags"):
        if key in item:
            values = item[key]
            if not isinstance(values, list) or len(values) > 1000 or any(not isinstance(v, str) for v in values):
                raise ValueError("Invalid public asset string list")
            result[key] = values
    for key in ("childPosts",):
        children = object_list(item, key, lambda child: post_metadata(child, depth + 1))
        if children is not None:
            result[key] = children
    return result


def public_metadata(actor: str, item: dict) -> dict:
    """Drop commenter/liker/follower identities, mentions/tags, related profiles and all unknown fields."""
    if actor not in ACTORS or not isinstance(item, dict):
        raise ValueError("Unknown actor/output policy")
    if actor in NEW_ACTORS:
        return new_metadata(actor, item, scalar_fields)
    if actor == "apify/instagram-scraper":
        return post_metadata(item)
    if actor == "apify/instagram-profile-scraper":
        result = scalar_fields(item, PROFILE)
        for key in ("latestPosts", "latestIgtvVideos"):
            posts = object_list(item, key, post_metadata)
            if posts is not None:
                result[key] = posts
        if "externalUrls" in item:
            urls = object_list(item, "externalUrls", lambda link: scalar_fields(link, {"url", "title", "link_type"}))
            if urls is not None:
                result["externalUrls"] = urls
        return result
    if actor == "apify/facebook-posts-scraper":
        result = scalar_fields(item, FB_POST)
        for key in ("user", "owner", "author"):
            if key in item and isinstance(item[key], dict):
                result[key] = scalar_fields(item[key], OWNER)
        media = object_list(item, "media", lambda asset: scalar_fields(asset, MEDIA))
        if media is not None:
            result["media"] = media
        if "reactions" in item and isinstance(item["reactions"], dict):
            result["reactions"] = {
                k: v
                for k, v in item["reactions"].items()
                if k.lower() in {"like", "love", "care", "haha", "wow", "sad", "angry"} and type(v) is int
            }
        return result
    result = scalar_fields(item, {"url", "searchQuery", "title", "resultsTotal", "searchTime"})
    if isinstance(item.get("searchQuery"), dict):
        result["searchQuery"] = scalar_fields(item["searchQuery"], {"term", "url", "page", "type"})
    organic = object_list(item, "organicResults", lambda hit: scalar_fields(hit, SEARCH))
    if organic is not None:
        result["organicResults"] = organic
    return result


class ProductionCollector:
    """The only paid start path: validate → reconcile → reserve → durable boundary → one POST."""

    def __init__(
        self,
        budget: ProductionBudget,
        transport: Transport,
        *,
        page_size: int = 100,
        read_workers: int = 8,
        hook: Callable[[str], None] = lambda event: None,
    ):
        self.budget = budget
        self.transport = transport
        self.page_size = bounded_int(page_size, 1, 1000, "page_size")
        self.read_workers = bounded_int(read_workers, 1, 32, "read_workers")
        self.hook = hook

    def status(self) -> dict:
        return self.budget.status()

    def reconcile(self, *, land: bool = True) -> dict:
        """Refresh every known bill, including already settled runs; failure never releases money."""
        known = [(batch_id, batch["run_id"]) for batch_id, batch in self.budget.status()["batches"].items()
                 if batch["run_id"]]
        pending_landings = []
        # Reads are independent; consume their results in ledger order so only the
        # caller mutates accounting. Any failed read still prevents a paid start.
        with ThreadPoolExecutor(max_workers=self.read_workers) as executor:
            reads = [executor.submit(self.transport.get_run, run_id) for _, run_id in known]
            for (batch_id, _), read in zip(known, reads, strict=True):
                observed = self.budget.observe(batch_id, read.result())
                if land and observed["status"] in TERMINAL and observed["dataset_id"] and not observed["landing"]:
                    pending_landings.append(batch_id)
            # Each worker owns a different immutable raw file; receipt commits
            # remain serialized. Failed downloads leave no partial raw envelope.
            downloads = [executor.submit(self._prepare_landing, batch_id) for batch_id in pending_landings]
            for batch_id, download in zip(pending_landings, downloads, strict=True):
                self._record_landing(batch_id, download.result())
        return self.budget.status()

    def run_batch(self, manifest: dict) -> dict:
        validated = validate_manifest(manifest, self.budget.clock())
        manifest = validated["manifest"]
        self.reconcile(land=False)
        batch = self.budget.reserve(manifest)
        batch_id = manifest["batch_id"]
        if batch["phase"] == "STARTING":
            raise AmbiguousStart("Persisted start has no run ID; reservation retained, recover without relaunching")
        if batch["phase"] == "RESERVED":
            self.hook("after_reserve")
            # Validate pins again immediately before the irreversible start boundary.
            validate_manifest(manifest, self.budget.clock())
            self.budget.begin_start(batch_id)
            self.hook("before_network")
            caps = {
                "maxTotalChargeUsd": str(money(manifest["max_total_charge_usd"])),
                "maxItems": manifest["max_items"],
                "timeout": manifest["timeout_s"],
                "memory": manifest["memory_mb"],
            }
            try:
                run = self.transport.start(manifest["actor"], manifest["input"], caps)
                if run["actId"] != validated["actor_id"]:
                    raise ValueError("Start response actor mismatch")
                self.budget.record_start_response(batch_id, run)
                self.hook("after_network")
                self.budget.verify_options(batch_id, run)
                self.budget.bind_run(batch_id, run["id"])
            except Exception as exc:  # noqa: BLE001 - any failure after the network boundary must retain the cap.
                # Persist fixed status/type diagnostics, never exception strings or remote bodies.
                if isinstance(exc, TransportFailure):
                    self.budget.record_diagnostic(batch_id, exc.diagnostic)
                elif not self.budget.batch(batch_id).get("safety_hold"):
                    self.budget.record_diagnostic(batch_id, {"kind": "start_boundary_failure", "operation": "start"})
                raise AmbiguousStart("Start outcome is uncertain; full reservation retained, no retry") from None
            batch = self.budget.observe(batch_id, run)
        else:
            batch = self.budget.batch(batch_id)
        if batch["status"] in TERMINAL and batch["dataset_id"] and not batch["landing"]:
            self.land(batch_id)
        return self.budget.batch(batch_id)

    def recover(self, batch_id: str, run_id: str) -> dict:
        """Bind only this attempt's durably pinned response, never a similar guessed run."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
            raise ValueError("Invalid recovery run ID")
        batch = self.budget.batch(batch_id)
        if batch["run_id"]:
            if batch["run_id"] != run_id:
                raise BudgetError("Batch is already bound to another run")
            self.reconcile()
            return self.budget.batch(batch_id)
        if batch["phase"] != "STARTING":
            raise BudgetError("Recovery is only for a persisted uncertain start")
        receipt = batch.get("start_response_receipt")
        if (not isinstance(receipt, dict) or receipt.get("schema_version") != 1
                or receipt.get("run_id") != run_id
                or receipt.get("manifest_sha256") != batch["manifest_sha256"]
                or receipt.get("input_sha256") != batch["manifest"]["input_sha256"]):
            raise BudgetError("No exact start response receipt; ambiguous reservation retained")
        checked = validate_manifest(batch["manifest"], self.budget.clock(), enforce_freshness=False)
        run = self.transport.get_run(run_id)
        if (
            run["id"] != run_id
            or run["actId"] != checked["actor_id"]
            or run["actId"] != receipt.get("actor_id")
            or run["startedAt"] != receipt.get("started_at")
            or timestamp(run["startedAt"]) < batch["start_boundary_at"] - 1
        ):
            raise BudgetError("Recovery actor/run/start time mismatch")
        remote_input = self.transport.get_input(run["defaultKeyValueStoreId"])
        if digest(remote_input) != batch["manifest"]["input_sha256"]:
            raise BudgetError("Recovery remote INPUT mismatch")
        self.budget.verify_options(batch_id, run)
        self.budget.bind_run(batch_id, run_id)
        observed = self.budget.observe(batch_id, run)
        if observed["status"] in TERMINAL and observed["dataset_id"]:
            self.land(batch_id)
        return self.budget.batch(batch_id)

    def land(self, batch_id: str) -> dict:
        """Paginate into a private atomic raw envelope only after projecting each public metadata record."""
        receipt = self._prepare_landing(batch_id)
        self._record_landing(batch_id, receipt)
        return receipt

    def _prepare_landing(self, batch_id: str) -> dict:
        """Read/project one dataset and commit its raw envelope without changing accounting."""
        batch = self.budget.batch(batch_id)
        if batch["status"] not in TERMINAL or not batch["dataset_id"]:
            raise BudgetError("Only a terminal bound run can land its dataset")
        if batch["landing"]:
            return batch["landing"]
        dataset_id = batch["dataset_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", dataset_id):
            raise ValueError("Invalid dataset ID")
        manifest = batch["manifest"]
        actor = manifest["actor"]
        if actor not in ACTORS:
            raise ValueError("Unknown actor output policy")
        target = self.budget.root / "raw" / "apify" / f"{batch_id}.json"
        count = 0
        if target.exists():
            envelope = json.loads(target.read_text())
            if (
                envelope["manifest_sha256"] != batch["manifest_sha256"]
                or envelope["run_id"] != batch["run_id"]
                or envelope["policy_version"] != POLICY_VERSION
                or envelope["dataset_id"] != dataset_id
                or len(envelope["items"]) > manifest["max_items"]
                or any(public_metadata(actor, item) != item for item in envelope["items"])
            ):
                raise BudgetError("Existing raw landing does not match its filtered immutable receipt")
            count = len(envelope["items"])
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".filtered-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    header = {
                        "schema_version": 1,
                        "policy_version": POLICY_VERSION,
                        "actor": actor,
                        "batch_id": batch_id,
                        "manifest_sha256": batch["manifest_sha256"],
                        "input_sha256": manifest["input_sha256"],
                        "run_id": batch["run_id"],
                        "dataset_id": dataset_id,
                        "fetched_at_epoch": self.budget.clock(),
                    }
                    if actor in NEW_ACTORS:
                        header["collection_input"] = manifest["input"]
                    stream.write(canonical(header)[:-1] + b',"items":[')
                    while count < manifest["max_items"]:
                        limit = min(self.page_size, manifest["max_items"] - count)
                        page = self.transport.dataset_page(dataset_id, count, limit)
                        if not isinstance(page, list) or len(page) > limit:
                            raise ValueError("Provider returned more than the bounded dataset page")
                        if not page:
                            break
                        for item in page:
                            retained = public_metadata(actor, item)
                            self.hook("before_filtered_write")
                            if count:
                                stream.write(b",")
                            stream.write(canonical(retained))
                            count += 1
                            if stream.tell() > 128 * 1024 * 1024:
                                raise ValueError("Filtered dataset exceeds the local byte ceiling")
                        # A short page is not assumed to prove EOF; continue from the returned offset.
                    stream.write(b"]}\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                self.hook("before_landing_commit")
                # Coordinator callers may reconcile concurrently: preserve the first identical landing.
                with self.budget.locked():
                    if target.exists():
                        if file_hash(Path(name)) != file_hash(target):
                            raise BudgetError("Concurrent immutable landing conflict")
                    else:
                        os.replace(name, target)
                        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(directory)
                        finally:
                            os.close(directory)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        receipt = {
            "path": str(target),
            "sha256": file_hash(target),
            "bytes": target.stat().st_size,
            "items": count,
            "policy_version": POLICY_VERSION,
            "source_url": f"{API}/datasets/{dataset_id}/items",
            "run_url": f"https://console.apify.com/view/runs/{batch['run_id']}",
        }
        return receipt

    def _record_landing(self, batch_id: str, receipt: dict) -> None:
        if self.budget.batch(batch_id)["landing"]:
            return
        self.hook("after_landing_commit")
        self.budget.record_landing(batch_id, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/home/vecera/code/agents007-hackathon/data/production"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--authorization", type=Path, required=True)
    init.add_argument("--authorization-sha256", required=True)
    init.add_argument("--accounting", type=Path, required=True)
    init.add_argument("--hold", type=Path, action="append", default=[])
    run = commands.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--accounting", type=Path)
    commands.add_parser("status")
    recover = commands.add_parser("recover")
    recover.add_argument("--batch-id", required=True)
    recover.add_argument("--run-id", required=True)
    args = parser.parse_args()
    budget = ProductionBudget(args.root)
    try:
        if args.command == "init":
            result = budget.initialize(
                args.authorization, args.authorization_sha256, args.accounting, hold_paths=tuple(args.hold)
            )
        elif args.command == "status":
            result = budget.status()
        else:
            collector = ProductionCollector(budget, ApifyTransport(os.environ.get("APIFY_TOKEN", "")))
            if args.command == "run":
                result = collector.run_batch(json.loads(args.manifest.read_text()))
            elif args.command == "recover":
                result = collector.recover(args.batch_id, args.run_id)
            else:
                if args.accounting:
                    budget.import_accounting(args.accounting)
                result = collector.reconcile()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (BudgetError, ValueError, KeyError, OSError, TypeError):
        # A transport/input exception may contain source content or a token. Inspect the safe ledger instead.
        parser.exit(2, "Production operation failed closed; inspect budget status. No automatic retries.\n")


if __name__ == "__main__":
    main()
