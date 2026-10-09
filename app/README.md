> Public checkout: run `./run.sh` from the repository root for the labelled simulated interface. The collected snapshot described below remains local and is not included. The root README is the current release guide.

# Starwatch

**Who's being heard. Not just who's talking.**

Starwatch maps the public posts, videos and quoted statements of the 2026 Czech city-council races. It covers 5,405 registered candidacies on 127 lists in ten cities, linked to the people and lists behind them.

- **Star Atlas:**
  - A full-bleed map of Czechia; pick a city and it flies into that town's detailed street map, with its real municipal boundary.
  - Each party is a floating island: logo, 2022 result, published forecast and its real posts sized by reach, biggest first.
  - Rank by reach, views, likes and comments, or posts. Click a party to open its island, or jump to the biggest candidate.
- **Spotlight:** portraits and party logos, 2022 candidate vote totals and list results, and published forecasts. The entity's best posts are sized by reach, with real video playback, quoted statements and links to sources.
- **Pulse:** people or lists side by side. A then-and-now view sets 2022 ballots, today's observed attention and published forecasts side by side, never combined into one score.
- **Radar:** observed changes for a watchlist over the city map, with suggested replies drafted for human review.
- **Studio:** evidence that worked, then a cited draft, then a live platform preview. Drafts are never posted.
- **By the numbers:** the verified posts available, how many play as video, and the observed views, likes and comments on them.

Every number opens the public source it was observed on.

Built in one night at Agents 0.0.7 (Prague, 8–9 October 2026), Social Media Deep Research track, by team DANDAPANDA.

## Run it

```sh
./run.sh            # exports the latest verified production checkpoint, then serves http://127.0.0.1:5173/
SKIP_EXPORT=1 ./run.sh   # serve without re-exporting
```

`run.sh` needs [uv](https://docs.astral.sh/uv/) for the export and the local server (`tools/serve.py`, which handles HTTP byte ranges so retained videos stream and seek). The app is dependency-free static HTML, CSS and JavaScript.

Checks (the server must be running):

```sh
node tools/check-atlas-c.mjs   # city picker, size filter, navigation, source links, real playback, platform coverage
node tools/walkthrough.mjs     # the demo path across all screens at 1920×1080 and 390×844
```

## Screens

| Screen | What it does |
| --- | --- |
| **Star Atlas** | MapLibre and OpenFreeMap base map (offline fallback: ČÚZK boundaries), city fly-in, party islands, rank by, topic lens, collapsible floating panels, inspector with real playback. |
| **Spotlight** | Field navigation rail (top in city, parties to ranked candidates), portrait header, 2022 votes, forecasts, reach-sized best posts, topics. |
| **Pulse** | ECharts comparisons, the then-and-now panel, top posts side by side with real video. |
| **Radar** | Watchlist over the city map, reach-sized alerts, proposed-answer sheet (never sent). |
| **Studio** | Evidence, then draft, then preview, with floating tools. Local templates only; no model connected. |
| **By the numbers** | Posts available in Starwatch, by platform, city and party. |

## Real, simulated and missing

Use the data badge in the top bar to switch between the two modes. Real mode never shows simulated content on real people.

- **Collected production snapshot (default when an export exists):**
  - The production run's latest verified checkpoint, read-only (`tools/export_real.py` → `web/data/real.js`).
  - All valid candidacies and lists are real registry records.
  - Assets appear only where independent checks confirmed the account owner.
  - Metrics are dated observations from recent profile samples, not complete histories.
  - Follower counts are single snapshots, so no growth is claimed.
  - Topics and claims appear only once reviewed; pending ones are labelled.
- **Local data at the recorded export:** checkpoint `production-native-006` (9 October 2026, about 06:10 Prague). It holds 10,697 verified public posts (8,961 Instagram, 1,736 Facebook) from 88 independently verified accounts.
  - 4,122 posts have a retained image and 2,178 have a retained video that plays in the app.
  - 172 source-labelled candidate portraits and 36 party logos are included.
  - Historical candidate totals and list results are drawn from ČSÚ open data where a match is available. Candidate totals include list-vote allocation; they are not preference-only votes. Identity and list-continuity limitations still apply.
  - Published forecasts cover 16 lists and 75 candidates, each with publisher, date and kind; betting markets are labelled as such.
  - The data was collected live during the hackathon by the Starwatch production run, using Apify Actors and independent ownership checks.
- **Platform coverage:** only Instagram and Facebook are observed, and only those appear in the app. TikTok, YouTube, X, news and web were not collected, and the app says so in one line. Shares appear only where a platform reports them.
- **Simulated universe (`?data=sim`):** generated names, lists, posts and metrics at the real per-city scale, to show the product at full coverage. It is labelled on every screen.
- **Not built yet:** complete posting histories, follower history (one snapshot per account), shares (not reported by the sampled sources), live scheduled collection inside the app, model-written briefs (Spotlight's brief is computed from observed counts) and any publishing integration for Radar and Studio drafts.

Starwatch describes observed public activity. Engagement measures attention, not support. It does not profile voters or commenters, and drafts are never posted automatically.

Real research data and retained media stay local and are not part of this repository.
