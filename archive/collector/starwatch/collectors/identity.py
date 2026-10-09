"""Resolve identity: find the subject's official accounts from the anchor and reject namesakes.

Two steps share one `IdentityBoard` kept on the run context:

- `ResolveIdentity` (stage 0) reads the anchor website, takes the social links it publishes as the
  official accounts, and settles each platform at once, so collection starts within seconds.
- `CheckLookalikes` runs beside the collectors. It searches Instagram and TikTok for the subject's
  name through Apify and judges every same-name account against the anchor: the account the site
  links to, a bio link to the anchor domain, the party or city in the bio, a verified badge.
  A platform the site does not link to waits for this search before its collector starts.

Accepted accounts carry their match basis. Rejected look-alikes carry a factual reason (another
website in the bio, "unofficial" in the bio, not the account the anchor links to). Anything else
stays `unconfirmed`, is never collected and is never guessed. Rejection describes an account's
relation to the anchor, never the person behind it; namesakes' posts and pictures are not read.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from ..models import PLATFORMS, Account, Platform, Rejected
from ..steps.base import RunContext, Step, StepResult
from .actors import ANCHOR_CRAWL, MAX_VIDEO_DOWNLOADS, SEARCHES, VIDEO_PLATFORMS
from .apify import ApifyRunFailed, run_actor
from .media import BROWSER_UA

log = logging.getLogger("starwatch.identity")

LABELS: dict[str, str] = {
    "website": "website", "facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok",
    "youtube": "YouTube", "x": "X",
}
SOCIAL: tuple[Platform, ...] = ("facebook", "instagram", "tiktok", "youtube", "x")
SITE_TIMEOUT_S = 8.0
SEARCH_WAIT_S = 120.0
MAX_REJECTED_PER_PLATFORM = 3
MAX_UNCONFIRMED_PER_PLATFORM = 1

# --- anchor ----------------------------------------------------------------------------------


@dataclass
class Anchor:
    text: str
    url: str = ""
    domain: str = ""
    terms: list[str] = field(default_factory=list)  # party, city or company ID when not a website

    @property
    def label(self) -> str:
        return self.domain or ", ".join(self.terms) or self.text


_DOMAIN = re.compile(r"^(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}(?:[/:?#].*)?$", re.IGNORECASE)


def parse_anchor(text: str) -> Anchor:
    text = text.strip()
    if " " not in text and _DOMAIN.match(text):
        url = text if re.match(r"^https?://", text, re.IGNORECASE) else f"https://{text}"
        return Anchor(text=text, url=url, domain=domain_of(url))
    terms = [t.strip() for t in re.split(r"[,;/]| a | and ", text) if len(t.strip()) >= 2]
    return Anchor(text=text, terms=terms or [text])


def domain_of(url: str | None) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(domain: str, anchor_domain: str) -> bool:
    return bool(domain and anchor_domain) and (domain == anchor_domain or domain.endswith("." + anchor_domain))


# --- social links on the anchor website --------------------------------------------------------


@dataclass(frozen=True)
class SocialLink:
    platform: Platform
    handle: str
    url: str


_SKIP_SEGMENTS: dict[str, set[str]] = {
    "facebook": {"sharer", "sharer.php", "share", "share.php", "dialog", "plugins", "tr", "policies",
                 "privacy", "help", "login", "l.php", "events", "groups", "hashtag", "photo",
                 "photo.php", "story.php", "permalink.php", "watch", "reel", "media", "business"},
    "instagram": {"p", "reel", "reels", "explore", "stories", "accounts", "tv", "direct", "about"},
    "tiktok": {"tag", "music", "discover", "embed", "share", "legal", "about"},
    "youtube": {"watch", "embed", "shorts", "playlist", "results", "feed", "redirect", "live",
                "about", "t", "howyoutubeworks"},
    "x": {"intent", "share", "home", "search", "hashtag", "i", "privacy", "tos", "login", "explore",
          "settings", "messages", "notifications"},
}


def parse_social_url(href: str) -> tuple[SocialLink, bool] | None:
    """(link, is_profile_link) for a social profile URL, or None. Post links name their page too."""
    try:
        parts = urlsplit(href.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") else host
    segments = [s for s in parts.path.split("/") if s]
    platform: Platform | None = {
        "facebook.com": "facebook", "fb.com": "facebook", "instagram.com": "instagram",
        "tiktok.com": "tiktok", "youtube.com": "youtube", "twitter.com": "x", "x.com": "x",
    }.get(host)  # type: ignore[assignment]
    if platform is None or not segments:
        return None
    first = segments[0]
    if first.lower() in _SKIP_SEGMENTS[platform]:
        return None
    is_profile = len(segments) == 1
    if platform == "facebook":
        if first == "profile.php":
            page_id = (parse_qs(parts.query).get("id") or [""])[0]
            if not page_id.isdigit():
                return None
            return SocialLink("facebook", page_id, f"https://www.facebook.com/profile.php?id={page_id}"), True
        if first == "pages" and len(segments) >= 3 and segments[-1].isdigit():
            return SocialLink("facebook", segments[-1], f"https://www.facebook.com/{segments[-1]}"), True
        is_profile = len(segments) == 1 or segments[1] in ("about", "photos", "videos", "reels", "posts") and len(segments) == 2
        return SocialLink("facebook", first, f"https://www.facebook.com/{first}"), is_profile
    if platform == "instagram":
        return SocialLink("instagram", first, f"https://www.instagram.com/{first}/"), is_profile
    if platform == "tiktok":
        if not first.startswith("@") or len(first) < 2:
            return None
        handle = first[1:]
        return SocialLink("tiktok", handle, f"https://www.tiktok.com/@{handle}"), is_profile
    if platform == "youtube":
        if first.startswith("@"):
            handle = first
            return SocialLink("youtube", handle, f"https://www.youtube.com/{handle}"), True
        if first in ("channel", "c", "user") and len(segments) >= 2:
            handle = f"{first}/{segments[1]}"
            return SocialLink("youtube", handle, f"https://www.youtube.com/{handle}"), True
        return None
    # x
    handle = first.lstrip("@")
    if not re.fullmatch(r"\w{1,15}", handle):
        return None
    return SocialLink("x", handle, f"https://x.com/{handle}"), is_profile


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []  # (href, text)
        self.title = ""
        self._in_title = False
        self._open: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._open = []
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            values = dict(attrs)
            if values.get("property") == "og:site_name" and values.get("content") and not self.title:
                self.title = values["content"] or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._open is not None:
            self.links.append((self._href, " ".join(self._open).strip()))
            self._open = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open.append(data.strip())
        if self._in_title and not self.title:
            self.title = data.strip()


_URL_IN_TEXT = re.compile(r"https?://[^\s)\]\"'<>]+")


def social_links(hrefs: list[str]) -> dict[Platform, SocialLink]:
    """The most-linked profile per platform. A page linked from a post link counts half."""
    scores: dict[tuple[Platform, str], float] = {}
    first_seen: dict[tuple[Platform, str], tuple[int, SocialLink]] = {}
    for index, href in enumerate(hrefs):
        parsed = parse_social_url(href)
        if not parsed:
            continue
        link, is_profile = parsed
        key = (link.platform, link.handle.lower())
        scores[key] = scores.get(key, 0.0) + (1.0 if is_profile else 0.5)
        first_seen.setdefault(key, (index, link))
    best: dict[Platform, SocialLink] = {}
    for key in sorted(scores, key=lambda k: (-scores[k], first_seen[k][0])):
        best.setdefault(key[0], first_seen[key][1])
    return best


@dataclass
class SiteRead:
    links: dict[Platform, SocialLink] = field(default_factory=dict)
    pages: list[str] = field(default_factory=list)
    title: str = ""
    final_url: str = ""
    error: str = ""
    via: str = "direct"  # direct | apify


_CONTACT = re.compile(r"kontakt|contact|o-?mne|about|socialn|sit[eě]|media", re.IGNORECASE)


async def read_site(url: str, client: httpx.AsyncClient) -> SiteRead:
    """Fetch the anchor's start page (and up to two contact pages when it links no profiles)."""
    read = SiteRead()
    hrefs: list[str] = []
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as error:
        read.error = _short_error(error)
        return read
    read.final_url = str(response.url)
    read.pages.append(read.final_url)
    parser = _LinkParser()
    parser.feed(response.text[:2_000_000])
    read.title = parser.title[:120]
    hrefs = [urljoin(read.final_url, h) for h, _ in parser.links if h]
    hrefs += _URL_IN_TEXT.findall(response.text)  # links built by scripts or in JSON-LD sameAs
    read.links = social_links(hrefs)
    if len(read.links) < 2:
        home = domain_of(read.final_url)
        contact = []
        for href, text in parser.links:
            full = urljoin(read.final_url, href)
            if same_site(domain_of(full), home) and (_CONTACT.search(href) or _CONTACT.search(text)):
                if full not in contact and full != read.final_url:
                    contact.append(full)
        for page in contact[:2]:
            try:
                extra = await client.get(page)
                extra.raise_for_status()
            except httpx.HTTPError:
                continue
            read.pages.append(str(extra.url))
            more = _LinkParser()
            more.feed(extra.text[:2_000_000])
            hrefs += [urljoin(str(extra.url), h) for h, _ in more.links if h]
            hrefs += _URL_IN_TEXT.findall(extra.text)
        read.links = social_links(hrefs)
    return read


def _short_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, httpx.TimeoutException):
        return "timed out"
    return type(error).__name__


# --- matching candidates against the anchor ------------------------------------------------------

_TITLES = {"bc", "mgr", "ing", "phdr", "judr", "mudr", "rndr", "doc", "prof", "phd", "csc", "mba",
           "dis", "paeddr", "mvdr", "dr", "arch", "ma", "msc", "ll", "m"}
_UNOFFICIAL = re.compile(
    r"neofici[aá]ln|unofficial|fan\s?page|fanpage|fan\s?club|fanklub|fan\s?account|parod|parody|"
    r"satir|not affiliated|nen[ií] ofici[aá]ln|nejsem\s+(?:pan|pan[ií])|meme",
    re.IGNORECASE,
)
_NEUTRAL_DOMAINS = {"linktr.ee", "linkin.bio", "beacons.ai", "bio.link", "lnk.bio", "msha.ke",
                    "linkfly.to", "taplink.cc", "allmylinks.com", "facebook.com", "instagram.com",
                    "tiktok.com", "youtube.com", "youtu.be", "x.com", "twitter.com", "threads.net",
                    "threads.com", "wa.me", "t.me"}
_DOMAIN_IN_TEXT = re.compile(r"(?<![@\w.])(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})(?:/\S*)?", re.IGNORECASE)


def fold(text: str) -> str:
    """Lowercase without diacritics, for comparing Czech names and bios."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def name_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", fold(text)) if t and t not in _TITLES]


NameMatch = Literal["exact", "contains", "handle"]


def name_match(subject: str, name: str, handle: str) -> NameMatch | None:
    want = name_tokens(subject)
    if not want:
        return None
    have = name_tokens(name)
    if have and sorted(have) == sorted(want):
        return "exact"
    if have and all(t in have for t in want):
        return "contains"
    # A handle matches when the name sits in it as whole words: petr.pavel23 and petrpavel.reality
    # do, pavel.petroff does not.
    flat = re.sub(r"[^a-z0-9]+", ".", fold(handle)).strip(".")
    for order in (want, list(reversed(want))):
        joined = r"\.?".join(re.escape(t) for t in order)
        if re.search(rf"(?:^|[.\d]){joined}(?:$|[.\d])", flat):
            return "handle"
    return None


@dataclass
class Candidate:
    platform: Platform
    handle: str
    url: str
    name: str = ""
    bio: str = ""
    link: str = ""  # the profile's website field
    verified: bool = False
    category: str = ""
    source: str = ""  # how it was found


@dataclass
class Verdict:
    status: Literal["accepted", "unconfirmed", "rejected", "official"]
    basis: list[str]
    reason: str = ""
    match: NameMatch | None = None


def bio_domains(candidate: Candidate) -> list[str]:
    found = [domain_of(candidate.link)] if candidate.link else []
    found += [domain_of(m.group(1)) for m in _DOMAIN_IN_TEXT.finditer(candidate.bio or "")]
    return [d for d in dict.fromkeys(found) if d and d not in _NEUTRAL_DOMAINS and "." in d]


def assess(candidate: Candidate, subject: str, anchor: Anchor, official: SocialLink | None) -> Verdict | None:
    """Judge one same-name account against the anchor. None: a different name, not a look-alike."""
    match = name_match(subject, candidate.name, candidate.handle)
    if official and candidate.handle.lower() == official.handle.lower():
        basis = []
        if candidate.verified:
            basis.append("verified badge")
        if any(same_site(d, anchor.domain) for d in bio_domains(candidate)):
            basis.append(f"bio links {anchor.domain}")
        return Verdict("official", basis, match=match or "exact")
    if match is None:
        return None
    domains = bio_domains(candidate)
    links_anchor = any(same_site(d, anchor.domain) for d in domains)
    elsewhere = [d for d in domains if not same_site(d, anchor.domain)]
    unofficial = _UNOFFICIAL.search(f"{candidate.handle} {candidate.name} {candidate.bio}")
    folded_bio = fold(candidate.bio or "")
    named_terms = [t for t in anchor.terms if len(t) >= 2 and fold(t) in folded_bio]

    details: list[str] = []
    if unofficial:
        details.append(f"bio says “{unofficial.group(0)}”")
    if elsewhere and not links_anchor:
        details.append(f"bio links {elsewhere[0]}")
    if candidate.category:
        details.append(f"profile category {candidate.category}")

    if official:
        reason = f"{anchor.label} links @{official.handle.lstrip('@')}, not this account"
        return Verdict("rejected", [], " · ".join([reason, *details]), match)
    if unofficial:
        return Verdict("rejected", [], " · ".join(details), match)
    if links_anchor:
        basis = [f"bio links {anchor.domain}", "name matches" if match != "handle" else "handle matches"]
        if candidate.verified:
            basis.append("verified badge")
        return Verdict("accepted", basis, match=match)
    if elsewhere:
        return Verdict("rejected", [], " · ".join([*details, f"nothing links it to {anchor.label}"]), match)
    if named_terms and candidate.verified and match in ("exact", "contains"):
        return Verdict("accepted", [f"bio names {named_terms[0]}", "verified badge", "name matches"], match=match)
    basis = ["same name"]
    if named_terms:
        basis.append(f"bio names {named_terms[0]}")
    if candidate.verified:
        basis.append("verified badge")
    basis.append(f"nothing links it to {anchor.label}")
    return Verdict("unconfirmed", basis, match=match)


def _category(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in ("none", "null") else text


def candidates_from_instagram(items: list[dict[str, Any]]) -> list[Candidate]:
    found = []
    for raw in items:
        handle = str(raw.get("username") or "")
        if not handle:
            continue
        found.append(Candidate(
            platform="instagram", handle=handle, url=f"https://www.instagram.com/{handle}/",
            name=str(raw.get("fullName") or ""), bio=str(raw.get("biography") or ""),
            link=str(raw.get("externalUrl") or ""), verified=bool(raw.get("verified")),
            category=_category(raw.get("businessCategoryName")), source="Instagram name search",
        ))
    return found


def candidates_from_tiktok(items: list[dict[str, Any]]) -> list[Candidate]:
    found = []
    for raw in items:
        meta = raw.get("authorMeta") or {}
        handle = str(meta.get("name") or "")
        if not handle:
            continue
        link = meta.get("bioLink")
        if isinstance(link, dict):
            link = link.get("link") or ""
        found.append(Candidate(
            platform="tiktok", handle=handle, url=f"https://www.tiktok.com/@{handle}",
            name=str(meta.get("nickName") or ""), bio=str(meta.get("signature") or ""),
            link=str(link or ""), verified=bool(meta.get("verified")), source="TikTok name search",
        ))
    return found


# --- the board shared by identity, collectors and the look-alike check ---------------------------


class VideoBudget:
    """Videos saved for transcription across lanes, filled in `VIDEO_PLATFORMS` order."""

    def __init__(self, total: int = MAX_VIDEO_DOWNLOADS, order: tuple[Platform, ...] = VIDEO_PLATFORMS):
        self.left = total
        self.order = order
        self._decided = {p: asyncio.Event() for p in order}

    async def claim(self, platform: Platform, wanted: int, wait_s: float = 90.0) -> int:
        if platform not in self.order:
            return 0
        for earlier in self.order[: self.order.index(platform)]:
            try:
                await asyncio.wait_for(self._decided[earlier].wait(), wait_s)
            except TimeoutError:
                pass
        granted = max(0, min(wanted, self.left))
        self.left -= granted
        self.decided(platform)
        return granted

    def decided(self, platform: Platform) -> None:
        if platform in self._decided:
            self._decided[platform].set()


@dataclass
class _Slot:
    account: Account | None = None
    reason: str = ""
    settled: asyncio.Event = field(default_factory=asyncio.Event)


class IdentityBoard:
    def __init__(self, ctx: RunContext, anchor: Anchor):
        self.ctx = ctx
        self.anchor = anchor
        self.official: dict[Platform, SocialLink] = {}
        self.slots: dict[Platform, _Slot] = {p: _Slot() for p in PLATFORMS}
        self.lanes: dict[Platform, asyncio.Event] = {p: asyncio.Event() for p in PLATFORMS}  # set when a lane ends
        self.unconfirmed: list[Account] = []
        self.rejected: list[Rejected] = []
        self.searches: dict[str, str] = {}  # platform -> status line
        self.search_tasks: list[asyncio.Task] = []
        self.videos = VideoBudget()
        self.site: SiteRead | None = None
        self._published = ""

    # accounts ---------------------------------------------------------------------------------
    def settle(self, platform: Platform, account: Account | None, reason: str = "") -> None:
        slot = self.slots[platform]
        if slot.settled.is_set():
            return
        slot.account, slot.reason = account, reason
        slot.settled.set()

    async def account_for(self, platform: Platform, wait_s: float = SEARCH_WAIT_S) -> tuple[Account | None, str]:
        slot = self.slots[platform]
        try:
            await asyncio.wait_for(slot.settled.wait(), wait_s)
        except TimeoutError:
            return None, f"identity search for {LABELS[platform]} did not finish in time"
        return slot.account, slot.reason

    def enrich(self, platform: Platform, *basis: str) -> None:
        """Add match basis seen while collecting (a verified badge, a link back to the anchor)."""
        account = self.slots[platform].account
        if account is None:
            return
        for line in basis:
            if line and line not in account.match_basis:
                account.match_basis.append(line)

    def reject_linked(self, platform: Platform, reason: str) -> None:
        """An account the anchor links to turned out not to be the subject's own: reject it."""
        slot = self.slots[platform]
        if slot.account is None:
            return
        self.rejected.insert(0, Rejected(url=slot.account.url, platform=platform, reason=reason))
        slot.account = None
        slot.reason = reason

    def accounts(self) -> list[Account]:
        accepted = [s.account for s in self.slots.values() if s.account is not None]
        return accepted + self.unconfirmed

    async def publish(self, **extra: Any) -> None:
        """Send the identity panel's current state; skipped when nothing changed."""
        accounts = self.accounts()
        self.ctx.accounts[:] = accounts
        self.ctx.rejected[:] = self.rejected
        payload = {
            "accounts": [a.model_dump() for a in accounts],
            "rejected": [r.model_dump() for r in self.rejected],
            "anchor": {"text": self.anchor.text, "url": self.anchor.url, "domain": self.anchor.domain,
                       "terms": self.anchor.terms, "site_title": self.site.title if self.site else "",
                       "read_via": self.site.via if self.site else "", "pages": self.site.pages if self.site else []},
            "searches": dict(self.searches),
            **extra,
        }
        fingerprint = repr(payload)
        if fingerprint == self._published:
            return
        self._published = fingerprint
        await self.ctx.data("identity", **payload)


def identity_board(ctx: RunContext) -> IdentityBoard | None:
    return ctx.__dict__.get("identity_board")


# --- steps ---------------------------------------------------------------------------------------


class ResolveIdentity(Step):
    id = "identity"
    label = "Resolve identity"
    group = "identity"

    async def run(self, ctx: RunContext) -> StepResult:
        token = ctx.credential("APIFY_TOKEN")
        anchor = parse_anchor(ctx.anchor)
        board = IdentityBoard(ctx, anchor)
        ctx.__dict__["identity_board"] = board

        if anchor.url:
            board.settle("website", Account(
                platform="website", url=anchor.url, handle=anchor.domain,
                match_basis=["the anchor given for this run"], status="accepted",
            ))
            async with httpx.AsyncClient(
                timeout=SITE_TIMEOUT_S, follow_redirects=True,
                headers={"User-Agent": BROWSER_UA, "Accept-Language": "cs,en;q=0.8"},
            ) as client:
                site = await read_site(anchor.url, client)
            if not site.links:
                site = await self._crawl_with_apify(ctx, token, anchor, site)
            board.site = site
            board.official = dict(site.links)
        else:
            board.settle("website", None, f"the anchor “{anchor.text}” is not a website")
            board.site = SiteRead(error="anchor is not a website")

        for platform in SOCIAL:
            link = board.official.get(platform)
            if link:
                where = board.site.pages[0] if board.site and board.site.pages else anchor.url
                board.settle(platform, Account(
                    platform=platform, url=link.url, handle=link.handle,
                    match_basis=[f"linked from {domain_of(where) or anchor.domain}"], status="accepted",
                ))
            elif platform not in SEARCHES:
                board.settle(platform, None, self._not_linked(anchor, platform))

        for platform, spec in SEARCHES.items():
            board.searches[platform] = "searching"
            task = asyncio.create_task(_search(board, platform, token))
            board.search_tasks.append(task)

        await board.publish()
        linked = [LABELS[p] for p in SOCIAL if p in board.official]
        site_note = ""
        if anchor.url and board.site and board.site.error and not board.site.links:
            site_note = f"{anchor.domain} could not be read ({board.site.error}); "
        if linked:
            note = f"{site_note}{anchor.domain} links {', '.join(linked)}; name search continues"
        elif anchor.url:
            note = f"{site_note}no social links on {anchor.domain}; name search continues"
        else:
            note = f"anchor is not a website; searching by name against “{anchor.text}”"
        return StepResult("done", count=len(linked), note=note)

    @staticmethod
    def _not_linked(anchor: Anchor, platform: Platform) -> str:
        if anchor.url:
            return f"no {LABELS[platform]} account linked from {anchor.domain}"
        return f"no {LABELS[platform]} account found for this anchor"

    async def _crawl_with_apify(self, ctx: RunContext, token: str, anchor: Anchor, direct: SiteRead) -> SiteRead:
        """The site refused a plain request or links nothing: crawl it once through Apify."""
        hrefs: list[str] = []
        pages: list[str] = []
        title = ""

        async def on_items(items: list[dict[str, Any]]) -> None:
            nonlocal title
            for item in items:
                pages.append(str(item.get("url") or ""))
                hrefs.extend(_URL_IN_TEXT.findall(str(item.get("markdown") or "")))
                title = title or str((item.get("metadata") or {}).get("title") or "")

        try:
            result = await run_actor(ANCHOR_CRAWL, {"startUrls": [{"url": anchor.url}]}, token=token, on_items=on_items)
            ctx.costs.apify_usd += result.usage_usd
            await _record_run(ctx, "identity.anchor", ANCHOR_CRAWL.actor_id, result.run_id, result.status, result.item_count, result.usage_usd)
        except ApifyRunFailed as failure:
            ctx.costs.apify_usd += failure.usage_usd
            await _record_run(ctx, "identity.anchor", ANCHOR_CRAWL.actor_id, failure.run_id, failure.status or "FAILED", 0, failure.usage_usd)
            direct.error = f"{direct.error or 'no links'}; Apify crawl failed"
            return direct
        links = social_links(hrefs)
        if not links:
            direct.error = direct.error or "no social links found"
            return direct
        return SiteRead(links=links, pages=[p for p in pages if p], title=title[:120], final_url=anchor.url, via="apify")


async def _search(board: IdentityBoard, platform: Platform, token: str) -> None:
    """Search one platform for the subject's name and judge every same-name account found."""
    ctx = board.ctx
    spec = SEARCHES[platform]
    run_input: dict[str, Any] = (
        {"search": ctx.subject} if platform == "instagram" else {"searchQueries": [ctx.subject]}
    )
    found: list[dict[str, Any]] = []

    async def on_items(items: list[dict[str, Any]]) -> None:
        found.extend(items)

    try:
        result = await run_actor(spec, run_input, token=token, on_items=on_items)
        ctx.costs.apify_usd += result.usage_usd
        await _record_run(ctx, f"identity.{platform}", spec.actor_id, result.run_id, result.status,
                          result.item_count, result.usage_usd)
    except ApifyRunFailed as failure:
        ctx.costs.apify_usd += failure.usage_usd
        await _record_run(ctx, f"identity.{platform}", spec.actor_id, failure.run_id, failure.status or "FAILED", 0, failure.usage_usd)
        board.searches[platform] = f"search failed: {failure}"[:200]
        board.settle(platform, None, f"{board.anchor.label} links no {LABELS[platform]} account and the name search failed")
        await board.publish()
        return
    except Exception as error:  # noqa: BLE001 - a failed search must never leave a collector waiting
        log.exception("identity search on %s failed", platform)
        board.searches[platform] = f"search failed: {type(error).__name__}"
        board.settle(platform, None, f"{board.anchor.label} links no {LABELS[platform]} account and the name search failed")
        await board.publish()
        return

    candidates = candidates_from_instagram(found) if platform == "instagram" else candidates_from_tiktok(found)
    official = board.official.get(platform)
    accepted: list[tuple[Candidate, Verdict]] = []
    unconfirmed: list[tuple[Candidate, Verdict]] = []
    rejected: list[tuple[Candidate, Verdict]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.handle.lower() in seen:
            continue
        seen.add(candidate.handle.lower())
        verdict = assess(candidate, ctx.subject, board.anchor, official)
        if verdict is None:
            continue
        if verdict.status == "official":
            board.enrich(platform, *verdict.basis)
        elif verdict.status == "accepted":
            accepted.append((candidate, verdict))
        elif verdict.status == "unconfirmed":
            unconfirmed.append((candidate, verdict))
        else:
            rejected.append((candidate, verdict))

    rank = {"exact": 0, "contains": 1, "handle": 2, None: 3}
    if accepted and not official:
        accepted.sort(key=lambda cv: (not cv[0].verified, rank[cv[1].match]))
        chosen, verdict = accepted[0]
        board.settle(platform, Account(platform=platform, url=chosen.url, handle=chosen.handle,
                                       match_basis=verdict.basis, status="accepted"))
        unconfirmed = [(c, Verdict("unconfirmed", ["same name", "a second account also links the anchor"], match=v.match))
                       for c, v in accepted[1:]] + unconfirmed
    for candidate, verdict in sorted(unconfirmed, key=lambda cv: rank[cv[1].match])[:MAX_UNCONFIRMED_PER_PLATFORM]:
        board.unconfirmed.append(Account(platform=platform, url=candidate.url, handle=candidate.handle,
                                         match_basis=verdict.basis, status="unconfirmed"))
    for candidate, verdict in sorted(rejected, key=lambda cv: rank[cv[1].match])[:MAX_REJECTED_PER_PLATFORM]:
        board.rejected.append(Rejected(url=candidate.url, platform=platform, reason=verdict.reason))

    n_lookalikes = len(rejected) + len(unconfirmed)
    board.searches[platform] = (
        f"{len(found)} profiles found for “{ctx.subject}”, {n_lookalikes} same-name look-alike"
        f"{'' if n_lookalikes == 1 else 's'}"
    )
    if not board.slots[platform].settled.is_set():
        if unconfirmed:
            n = len(unconfirmed)
            reason = (f"{board.anchor.label} links no {LABELS[platform]} account; the name search found "
                      f"{n} same-name account{'s' if n > 1 else ''}, none tied to {board.anchor.label}, so none collected")
        else:
            reason = f"{board.anchor.label} links no {LABELS[platform]} account and the name search found none that matches"
        board.settle(platform, None, reason)
    await board.publish()


async def _record_run(ctx: RunContext, lane: str, actor: str, run_id: str, status: str, items: int, usage: float) -> None:
    runs = ctx.__dict__.setdefault("apify_runs", [])
    runs.append({"lane": lane, "actor": actor, "run_id": run_id, "status": status, "items": items,
                 "usage_usd": round(usage, 5), "console_url": f"https://console.apify.com/view/runs/{run_id}"})
    ctx.save_json("apify_runs.json", runs)
    await ctx.data(lane, usage_usd=round(usage, 5), costs=ctx.costs.model_dump(), actor_run_id=run_id)


class CheckLookalikes(Step):
    """Runs beside the collectors until the name searches have judged every same-name account."""

    id = "identity.lookalikes"
    label = "Check look-alikes"
    group = "identity"
    actor = "apify/instagram-scraper · clockworks/tiktok-scraper"

    async def run(self, ctx: RunContext) -> StepResult:
        ctx.credential("APIFY_TOKEN")
        board = identity_board(ctx)
        if board is None:
            return StepResult("skipped", note="identity did not run")
        if board.search_tasks:
            await asyncio.wait(board.search_tasks, timeout=SEARCH_WAIT_S + 30)
        for platform, slot in board.slots.items():
            if not slot.settled.is_set():
                board.settle(platform, None, f"identity search for {LABELS[platform]} did not finish in time")
        await board.publish()
        searched = ", ".join(LABELS[p] for p in board.searches)
        note = (f"{len(board.rejected)} rejected, {len(board.unconfirmed)} unconfirmed · "
                f"searched {searched} by name")
        return StepResult("done", count=len(board.rejected), note=note)
