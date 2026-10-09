# Apify recipes

Starwatch reuses Apify Actors instead of writing its own scrapers. This page documents every Actor that actually ran during the hackathon night of 8–9 October 2026: what it was for, the exact input, the output fields Starwatch keeps, what it cost, how long it took, what went wrong and how the code calls it. The runnable inputs are in [recipes/apify/](../recipes/apify/).

All prices below are the Apify Bronze tier as observed on 8–9 October 2026, read from the Actors' live pricing and confirmed against the charged event counts of real runs. Prices change; check the Actor page before you plan a batch.

## Summary

The production run on 9 October made 56 Actor runs between 03:42 and 06:35 Prague time and settled at $91.17 in Actor charges. Before that, the exploration lane spent $2.84 in 13 runs and the live collector spent $1.33 in 42 runs, including tests.

| Actor | Starwatch use | Production runs | Items | Charged | Unit price |
| --- | --- | ---: | ---: | ---: | --- |
| [`apify/instagram-scraper`](https://apify.com/apify/instagram-scraper) | Post history of verified Instagram accounts; name search for look-alikes | 19 | 20,576 posts | $47.32 | $0.0023 per result |
| [`apify/facebook-posts-scraper`](https://apify.com/apify/facebook-posts-scraper) | Post history of verified Facebook pages and profiles | 12 | 9,302 posts | $37.22 | $0.004 per post + $0.001 per run |
| [`apify/google-search-scraper`](https://apify.com/apify/google-search-scraper) | Discovery of official websites, social accounts, portraits and news | 17 | 1,662 result pages | $4.16 | $0.0025 per page + $0.00005 per run |
| [`clockworks/tiktok-scraper`](https://apify.com/clockworks/tiktok-scraper) | TikTok videos of verified accounts; live collector lane | 1 | 598 videos | $1.80 | $0.003 per result + $0.001 per run |
| [`apify/instagram-profile-scraper`](https://apify.com/apify/instagram-profile-scraper) | Public/private status, follower snapshot and latest posts per profile | 5 | 171 profiles | $0.39 | $0.0023 per profile |
| [`streamers/youtube-scraper`](https://apify.com/streamers/youtube-scraper) | Video metadata of website-linked channels | 1 | 47 videos | $0.14 | $0.003 per video |
| [`apidojo/twitter-scraper-lite`](https://apify.com/apidojo/twitter-scraper-lite) | Media posts from verified X accounts | 1 | 274 posts | $0.14 | $0.016 per query + $0.0004 per item beyond the ~40 included |
| [`clockworks/tiktok-profile-scraper`](https://apify.com/clockworks/tiktok-profile-scraper) | Exploration: latest videos and their subtitle links | 0 (3 in exploration) | 50 videos | $0.10 | $0.002 per result |
| [`apify/website-content-crawler`](https://apify.com/apify/website-content-crawler) | Live collector: the subject's own website and anchor fallback | 0 (4 in the collector) | 64 pages | $0.01 | platform usage |

Three more Actors appear in the exploration code (`apify/facebook-pages-scraper`, `streamers/youtube-channel-scraper`, `apidojo/tweet-scraper`) but were never run. They are not documented as recipes.

## How to run a recipe

Each file in `recipes/apify/` is the request body for a run. Pass the run limits as query parameters so Apify enforces them even if an input field is wrong. Keep the token in an environment variable and send it as a header.

```python
import json, os, urllib.request

actor = "apify~instagram-scraper"  # owner~name
body = open("recipes/apify/apify--instagram-scraper.json", "rb").read()
url = (f"https://api.apify.com/v2/acts/{actor}/runs"
       "?maxItems=200&maxTotalChargeUsd=0.50&timeout=900&memory=1024")
request = urllib.request.Request(url, data=body, method="POST", headers={
    "Authorization": f"Bearer {os.environ['APIFY_TOKEN']}",
    "Content-Type": "application/json",
})
print(json.load(urllib.request.urlopen(request))["data"]["id"])
```

Read results with `GET /v2/datasets/{datasetId}/items?fields=...` and name only the fields you need. Several Actors return comments and other people's data by default; the `fields` allowlist keeps it off your disk.

## How the code calls Apify

Starwatch has three callers, one per phase of the night. All three set `maxItems` and `maxTotalChargeUsd` on every run and read the token from `APIFY_TOKEN`.

The live collector ([collector/starwatch/collectors/apify.py](../collector/starwatch/collectors/apify.py), specs in [actors.py](../collector/starwatch/collectors/actors.py)) starts one run per platform lane, polls the run's dataset every couple of seconds with a `fields` allowlist, streams new items to the screen, aborts once the item cap has arrived and keeps whatever a slow run delivered before its timeout. A separate `SettleCosts` step ([costs.py](../collector/starwatch/collectors/costs.py)) re-reads every run after collection, because Apify updates `usageTotalUsd` a few seconds after a run stops.

The exploration lakehouse ([pipeline/src/czlake/apify_run.py](../pipeline/src/czlake/apify_run.py)) wraps each run in a file-locked ledger. Committed spend counts finished runs at their real usage and in-flight runs at their full `maxTotalChargeUsd`, so the lane could never pass its $20 cap. Each raw dataset lands as JSON with its run ID; [build/collect_social.py](../pipeline/src/czlake/build/collect_social.py), [build/discover_accounts.py](../pipeline/src/czlake/build/discover_accounts.py) and [build/discover_local.py](../pipeline/src/czlake/build/discover_local.py) build the inputs.

The production run ([pipeline/src/czlake/production_collect.py](../pipeline/src/czlake/production_collect.py), ledger in [production_budget.py](../pipeline/src/czlake/production_budget.py)) works from sealed manifests. A manifest pins the Actor, the exact input and its SHA-256, the item cap, timeout, memory, provider spending cap, purpose and a pinned price snapshot with the expected upper cost. `run --manifest PATH` validates the input against the Actor's live schema, reserves the cap, writes a durable start boundary, makes exactly one POST and never retries. `reconcile` settles each run from its charged event counts, and dataset pages pass through the `public_metadata` allowlist before anything is written. Other subcommands are `init`, `status` and `recover`.

## apify/instagram-scraper

**Purpose.** The workhorse of the production run. It collected the post history of every Instagram account that passed the ownership review, plus qualifying local party/list accounts. In the live collector it also ran name searches that surface look-alike accounts for the identity check.

**Input.** [apify--instagram-scraper.json](../recipes/apify/apify--instagram-scraper.json): `directUrls` of verified profiles, `resultsType: "posts"`, `resultsLimit` per account and `addParentData: false`. Production used `resultsLimit` of 20 (people with no posts yet), 30 with `onlyPostsNewerThan` set to one month back, 100 (history) and 400 (depth for the most active verified people), in batches of up to 20 accounts. The live collector used `resultsLimit: 30`. The identity search variant was:

```json
{"search": "<full name>", "searchType": "user", "searchLimit": 6, "resultsType": "details", "resultsLimit": 1}
```

**Output fields kept.** `id`, `shortCode`, `type`, `productType`, `url`, `timestamp`, `caption`, `alt`, `ownerId`, `ownerUsername`, `ownerFullName`, `displayUrl`, `videoUrl`, `videoViewCount`, `videoPlayCount`, `likesCount`, `commentsCount`, `dimensionsHeight`, `dimensionsWidth`, `isCommentsDisabled`, `videoDuration`, `images`, `hashtags` and nested `childPosts` with the same fields. Comment previews (`latestComments`, `firstComment`), tagged users and mentions are dropped.

**Cost and time.** $0.0023 per returned post; there is no start fee. 20 accounts × 100 posts took 10–14 minutes and returned 1,058–1,912 posts per batch. 20 accounts × 20 posts took about 3 minutes. The two 400-post batches of 10 accounts hit the 900-second timeout at about 17 minutes and still delivered 3,292 and 2,920 posts, which were kept and billed.

**Failure modes and fixes.** Comment previews come back by default, so every read uses an allowlist. Image and video URLs are signed CDN links that expire, and Instagram blocks hotlinking, so media is downloaded at collection time, bounded by size and checked by hash. A post returned for a requested profile is admitted only when its `ownerUsername` matches the reviewed account; profile bundles from other accounts stay association evidence. Deep-history batches should be split so they finish inside the timeout.

## apify/facebook-posts-scraper

**Purpose.** Post history of verified Facebook pages and profiles, which turned out to be the main public channel for many local candidates.

**Input.** [apify--facebook-posts-scraper.json](../recipes/apify/apify--facebook-posts-scraper.json): `startUrls`, `resultsLimit` per page and `captionText: false`. Production used 5 (first proof), 20, 50, 100 and 400 posts per page, with up to 20 pages per run.

**Output fields kept.** `id`, `postId`, `url`, `postUrl`, `facebookUrl`, `pageId`, `pageName`, `userId`, `username`, `text`, `time`, `timestamp`, `likes`, `comments`, `shares`, `views`, `videoViews`, `isVideo`, `isLiveVideo`, `thumbnailUrl`, `videoUrl`, `imageUrl`, `topLevelUrl`, `inputUrl`, `isSponsored`, `isShare`, the author object (`id`, `name`, `username`, `profileUrl`, `profilePic`, `verified`), `media` items and the seven reaction counts. `topComments` is dropped.

**Cost and time.** $0.004 per post plus $0.001 per run. The date filter adds $0.001 per post, so Starwatch filtered dates locally instead. Up to 20 pages × 100 posts took about 7 minutes and returned 866–1,901 posts; up to 20 pages × 20 posts took 1–3 minutes; 5 pages × 400 posts took about 12 minutes.

**Failure modes and fixes.** In the first five-post proof, four posts carried an author ID different from the requested page; collection yield is not authorship. Starwatch binds a reviewed vanity URL to the page's numeric ID through its public profile metadata and admits a post only when its returned author matches that ID ([production_facebook_binding.py](../pipeline/src/czlake/production_facebook_binding.py)). `profile.php` URLs were skipped in the exploration code. One party's Facebook page ID was shared across city and district pages, so its scope stays unknown.

## apify/google-search-scraper

**Purpose.** Cheap discovery. It found candidates' official websites (anchors for identity), Instagram and Facebook leads, portrait sources and news mentions. Results are leads, never ownership evidence.

**Input.** [apify--google-search-scraper.json](../recipes/apify/apify--google-search-scraper.json): newline-separated `queries`, one page per query, Czech locale and every paid add-on disabled (AI overview, AI mode, Gemini, Perplexity, ChatGPT, Copilot, leads enrichment, link prospecting, website content, HTML saving). The query templates were:

| Purpose | Query template |
| --- | --- |
| Official website anchor | `"<name>" "<city>" politik oficiální web` |
| Social accounts | `"<name>" "<city>" (instagram OR facebook)` |
| Portrait sources | `"<name>" "<city>" kandidát portrét fotografie` |
| News mentions | `"<name>" "<city>" (rozhovor OR zpráva OR zastupitelstvo)` |
| Exploration, national tier | `"<name>" senátor (site:facebook.com OR site:instagram.com OR site:tiktok.com OR site:youtube.com OR site:x.com OR site:twitter.com)` |

**Output fields kept.** `url`, `searchQuery` (`term`, `url`, `page`, `type`), `title`, `resultsTotal`, `searchTime` and `organicResults` with `url`, `title`, `description`, `snippet`, `position`, `displayedUrl` and `date`.

**Cost and time.** $0.0025 per result page plus $0.00005 per run; one query is one page with several organic hits. Batches of 100–175 queries took 4–15 minutes. Exploration retained 1,054 pages for $2.64.

**Failure modes and fixes.** The Actor refuses a `maxTotalChargeUsd` below $0.50, so small batches carry a $0.50 cap. Two exploration batches were still running when I paused collection; they were aborted cleanly, still billed for the 199 and 200 pages they delivered, and those datasets were recovered read-only instead of rerunning. In production one start returned an error after the start boundary had been written; it has no run ID, so its $0.08 reservation stayed held and none of its queries were retried blindly.

## clockworks/tiktok-scraper

**Purpose.** TikTok videos for verified accounts in production, and three jobs in the live collector: the TikTok lane, a name search for look-alikes, and fetching a few video files for transcription.

**Input.** [clockworks--tiktok-scraper.json](../recipes/apify/clockworks--tiktok-scraper.json): `profiles`, `resultsPerPage`, `profileScrapeSections: ["videos"]`, `profileSorting: "latest"` and every extra explicitly off (comments, followers, downloads, related videos, AI summaries, subtitles). Production pulled up to 200 latest videos from four accounts. The collector variants were:

```json
{"profiles": ["<handle>"], "resultsPerPage": 20, "profileSorting": "latest", "shouldDownloadVideos": false}
{"searchQueries": ["<full name>"], "searchSection": "/user", "maxProfilesPerQuery": 6, "resultsPerPage": 1}
{"postURLs": ["<video url>"], "shouldDownloadVideos": true}
```

All three also set the comment, follower, cover, avatar, subtitle and AI switches off, as in the recipe file.

**Output fields kept.** `id`, `webVideoUrl`, `text`, `createTime`, `createTimeISO`, `diggCount`, `playCount`, `shareCount`, `commentCount`, `collectCount`, `repostCount`, `isSlideshow`, `isPinned`, `isStory`, and from `authorMeta`: `id`, `name`, `nickName`, `profileUrl`, `privateAccount`, `avatar`, `verified`, `fans`, `following`, `heart`, `video`.

**Cost and time.** $0.003 per result plus $0.001 per run; video download adds $0.001 per result and transcription $0.041 per started minute, both off. Four profiles returned 598 videos in 7 minutes with 4096 MB. In the collector, 20 posts cost about $0.06 and the first item arrived in about 15 seconds.

**Failure modes and fixes.** The Actor refuses `maxTotalChargeUsd` below $0.50; the skeleton's $0.12 cap made every TikTok run fail with a 400, so the cap sits at the minimum and `maxItems` keeps the real cost low. With the video add-on on, every item waits until its video is saved and the first item arrives after about 80 seconds instead of 15, so posts stream without videos and a second run fetches at most three videos by URL. This Actor's price differs from `tiktok-profile-scraper`; do not reuse one Actor's price for the other.

## apify/instagram-profile-scraper

**Purpose.** The cheapest broad pass: one billed event per profile returns the bio, external links, public/private status, a dated follower count and a bundle of latest posts. Starwatch used it for the first shortlist checks, the bounded ten-city sample and public metadata of newly discovered handles.

**Input.** [apify--instagram-profile-scraper.json](../recipes/apify/apify--instagram-profile-scraper.json): `usernames` and `includeAboutSection: false`.

**Output fields kept.** `id`, `fbid`, `username`, `fullName`, `biography`, `url`, `inputUrl`, `externalUrl`, `externalUrls`, `followersCount`, `followsCount`, `postsCount`, `profilePicUrl`, `profilePicUrlHD`, `verified`, `private`, `isBusinessAccount`, `businessCategoryName`, `highlightReelCount`, `igtvVideoCount`, plus `latestPosts` and `latestIgtvVideos` reduced to the Instagram post fields above.

**Cost and time.** $0.0023 per profile; the About section would add $0.006 per profile and stays off. Nine profiles took 22 seconds; 47 profiles 83 seconds; 80 profiles 93 seconds. Eleven profiles for $0.0253 returned 132 bundled posts.

**Failure modes and fixes.** Twelve latest posts per profile was what we observed, not a guaranteed history, and pinned posts can be years old. Bundled posts prove nothing about authorship until the profile itself is anchored. A sizing estimate based on Facebook posts suggested $88 for a broad sample; reading the real bills showed this bundle was the cheap baseline, and the plan changed.

## streamers/youtube-scraper

**Purpose.** Video metadata of YouTube channels linked from a candidate's own website, and the YouTube lane of the live collector.

**Input.** [streamers--youtube-scraper.json](../recipes/apify/streamers--youtube-scraper.json): channel `startUrls`, `maxResults` 250, `maxResultsShorts` 50, no streams, newest first, and transcription, subtitles and AI descriptions off. The collector used 6 videos and 4 shorts per channel.

**Output fields kept.** `id`, `type`, `title`, `text`, `description`, `url`, `duration`, `date`, `viewCount`, `likes`, `commentsCount`, `thumbnailUrl`, `isShort`, availability flags and channel fields (`channelId`, `channelName`, `channelUrl`, `channelUsername`, `numberOfSubscribers`, `isChannelVerified`).

**Cost and time.** $0.003 per video; the date filter adds $0.001 and ASR $0.041 per started minute. Three channels returned 47 videos in under 7 minutes for $0.14.

**Failure modes and fixes.** A website can link an institutional channel. The first live test linked a government channel from a politician's site; a display-name check rejected it. The 47 production videos are retained but were not admitted into the launch snapshot because the final channel-ownership review was not finished, so YouTube shows one verified account and no posts.

## apidojo/twitter-scraper-lite

**Purpose.** Media posts from X accounts that passed the ownership review, and the X lane of the live collector.

**Input.** [apidojo--twitter-scraper-lite.json](../recipes/apify/apidojo--twitter-scraper-lite.json): one `from:<handle> filter:media -filter:replies -filter:retweets` search term per account, `sort: "Latest"`, `includeSearchTerms: true` and a global `maxItems`. Production ran five terms with `maxItems` 6000; the production code accepts only that exact query shape and one to five terms. The live collector lane used `{"twitterHandles": ["<handle>"], "maxItems": 30, "sort": "Latest"}`.

**Output fields kept.** `id`, `url`, `twitterUrl`, `createdAt`, `text`, `fullText`, `lang`, `isReply`, `isRetweet`, `isQuote`, `isPinned`, `likeCount`, `quoteCount`, `replyCount`, `retweetCount`, `viewCount`, `bookmarkCount`, and from `author`: `id`, `userName`, `name`, `url`, `profilePicture`, `protected`, `followers`, `following`, `mediaCount`, `statusesCount`, `isVerified`, `isBlueVerified`, `createdAt`.

**Cost and time.** $0.016 per query, which includes roughly the first 40 results, plus $0.0004 per further item; a single-tweet URL query costs $0.05. Five queries returned 274 posts in about 7 minutes with 256 MB and were billed $0.08 + 147 × $0.0004 = $0.14, far under the $2.48 upper estimate.

**Failure modes and fixes.** A name query is a discovery lead, not a publisher. Original posts, replies, reposts and quotes are separate kinds; the query excludes replies and reposts, and quote targets keep their own author.

## clockworks/tiktok-profile-scraper

**Purpose.** Exploration only: the latest five videos of shortlisted national politicians, mainly to see which ones have usable speech.

**Input.** [clockworks--tiktok-profile-scraper.json](../recipes/apify/clockworks--tiktok-profile-scraper.json): `profiles`, `resultsPerPage` 5, latest first, pinned posts excluded, downloads, comments and follower lists off.

**Output fields used.** Video ID, text, time, URL, counts, author metadata and `videoMeta.subtitleLinks`, which include TikTok's own Czech ASR track (`ces-CZ`) with timecodes.

**Cost and time.** $0.002 per result; the date filter adds $0.001. Eight profiles × 5 videos cost $0.08.

**Failure modes and fixes.** The subtitle links expire within hours, so [build/tiktok_subs.py](../pipeline/src/czlake/build/tiktok_subs.py) fetches the Czech and Slovak tracks right after the run; 33 of the first 40 videos had a usable track. A background job started from the wrong directory lost its project and ran twice, costing an extra $0.01; background commands now pass the project path explicitly.

## apify/website-content-crawler

**Purpose.** The live collector's website lane (the subject's own site as an asset) and a fallback for reading the anchor website when a direct request is refused.

**Input.** [apify--website-content-crawler.json](../recipes/apify/apify--website-content-crawler.json): depth 1, at most 15 pages, the fast Cheerio crawler, 20-second request timeout, one retry, no Markdown or HTML saved. The anchor fallback crawls only the start page with `playwright:firefox`, strips scripts and keeps Markdown, because official social links usually sit in the header and footer:

```json
{"startUrls": [{"url": "<anchor website>"}], "maxCrawlDepth": 0, "maxCrawlPages": 3, "crawlerType": "playwright:firefox", "proxyConfiguration": {"useApifyProxy": true}, "removeElementsCssSelector": "script, style, noscript", "htmlTransformer": "none", "saveMarkdown": true}
```

**Output fields kept.** `url`, `crawl`, `metadata`, `text` (lane) or `markdown` (fallback).

**Cost and time.** Platform usage only; four collector runs returned 64 pages for about $0.01. A slow site held one run for 146 seconds, so the lane now stops at 75 seconds and keeps what arrived.

**Failure modes and fixes.** Reading the anchor directly takes about 0.3 seconds and is tried first; the crawler is the fallback. Some political sites reject direct clients with 403, and one old campaign domain redirected to unrelated betting content and had to be rejected as an anchor.

## Other sources

Not everything came from Apify. These sources were fetched directly and are free unless noted.

| Source | What Starwatch takes from it | URL |
| --- | --- | --- |
| Czech Statistical Office election open data | 2026 municipal candidate registry (dated 7 October 2026), 2022 municipal results, and registries/results of 15 elections back to 2018 for history | [volby.gov.cz/opendata](https://volby.gov.cz/opendata/) |
| ČSÚ population | Population of every municipality on 1 January 2026, used to pick the ten largest cities | [OBY02A dataset](https://data.csu.gov.cz/opendata/sady/OBY02A/distribuce/csv) |
| Wikidata | Politicians' and parties' published social handles, websites and party IČO, as dated leads (CC0) | [query.wikidata.org](https://query.wikidata.org/) |
| TikTok subtitle tracks | TikTok's own Czech ASR captions with timecodes, linked from Actor output | [tiktok.com](https://www.tiktok.com/) |
| ElevenLabs Scribe v2 | Word-level Czech transcripts of three short videos in the live collector, 2.6 minutes in total, `scribe_v2`, language `cs`, no diarization | [elevenlabs.io speech-to-text](https://elevenlabs.io/docs/api-reference/speech-to-text) |
| Exa | Discovery of official pages, programmes and news articles during the source audit and later research; paid per search | [exa.ai](https://exa.ai/) |
| Official party and candidate websites | Exact links to social accounts (identity anchors), candidate pages, programmes | fetched directly, bounded |
| Wikimedia Commons | National party logos with recorded licences | [commons.wikimedia.org](https://commons.wikimedia.org/) |
| ČÚZK boundaries and OpenFreeMap | City boundaries for the map and the base map tiles | [cuzk.cz](https://cuzk.gov.cz/), [openfreemap.org](https://openfreemap.org/) |

[Data sources](data-sources.md) describes each source's licence, date and role in more detail. Party programmes and news articles for the launch are documented in [collection/programs-and-articles.md](collection/programs-and-articles.md).
