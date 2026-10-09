# How Starwatch was built

I built Starwatch alone, as team DANDAPANDA, during one night at the Agents 0.0.7 hackathon in Prague on 8–9 October 2026, and launched it publicly the same day. This is the honest version: what I set out to do, what changed, how a few dozen AI agents were organised, what the data run cost, what broke, and what is live, cached or missing today. All times are Prague time (CEST).

## The brief

The event was "From Dusk Till Dawn", hackathon #01 of Agents 0.0.7. Kick-off was at 17:30 on 8 October, code freeze and submission at sunrise, 07:14 on 9 October, presentations at 10:00. I picked the Social Media Deep Research track, run with Apify. Its brief: take a person or organisation, an identifying anchor such as a website or city, and a research goal; produce a report with source links for every claim, a visible line between fact and inference, and visible gaps. Handle namesakes. Reuse Apify Actors instead of writing scrapers. Public sources only: no private groups, no fake accounts, no personality or trustworthiness scoring, no inference of sensitive traits. Raw scraped data is to be deleted after judging.

The timing made the topic obvious. Czech municipal elections were on 9–10 October, the same weekend. I wanted a tool that shows who among the candidates in Czech cities actually gets public attention, what they publish, and where every number comes from.

## The night, decision by decision

| Time | What happened |
| --- | --- |
| 8 Oct, evening | Six deep-research reports (three prompts, each in Claude Research and ChatGPT Deep Research) on comparable products, public-activity metrics and demo flow. Two Apify test runs (website crawler, Facebook posts) to check the basics. |
| 22:29 | Read the HQ rules, judging weights and submission requirements into a local event record. |
| 23:04 | Green light on the first plan, "War Room": live research on one public politician who is not on the weekend's ballot, with briefs that change when the research goal changes. |
| 23:14 | Named it Starwatch. Eight other candidate names were already taken by research, political or game products. |
| 23:20 | Threw away my earlier Figma concepts and started the visual identity from a design prompt with three directions: a star atlas, a newspaper desk, a wildcard. |
| 23:32 | First commit. Head of staff and worker agent definitions in place. |
| 23:43 | Authorised an exploration run with a $20 Apify cap: an official-data lakehouse for the 100 largest Czech municipalities. |
| 23:49 | App skeleton: an input screen with six Apify lanes streaming over server-sent events. |
| 00:10 | First data milestone: the ČSÚ top-100 municipality universe (48.2% of the population) and a shortlist of five national politicians checked against the 9–10 October candidate registries. |
| 00:15–00:25 | Live collection worked early. A test run on a former prime minister's website found his official accounts, rejected nine look-alikes and one institutional channel his site links to, and streamed 120 items with images in 47 seconds for $0.29. |
| 00:35–00:53 | Three ElevenLabs Scribe transcripts and eighteen TikTok caption tracks; cached briefs for three research goals whose quotes and timecodes passed verification. Two goals on the same subject cited completely different sources. |
| 00:43 | Paused paid collection and asked for a cost audit from real bills before spending more. |
| 00:47 | Narrowed the research to the ten largest cities and asked for a deterministic rule for whom to research first. |
| ~01:25 | Chose Atlas, the map-first direction, as the product. |
| 01:38 | Authorised a bounded ten-city sample with a $0.07 cap. |
| 02:06 | Set the overall overnight ceiling at $120. |
| 02:26 | Rescoped the product: a map of Czechia, then city, then people and party lists, then their posts and videos; claims linked to topics; metrics as dated observations. Dropped the goal-switch storyboard, the countdowns and the invented milestones. |
| 03:29 | Authorised the production data run: $100 inside the $120 ceiling. Selection rule revised so that being first on a list no longer qualifies anyone on its own. |
| 03:42 | First paid production batch. |
| 04:20 | First version of the app built on the first verified checkpoint. |
| ~04:55 | Chose the light "Atlas C" design and the aperture star mark; the dark star-field look was retired. |
| 05:45–06:35 | Anti-slop design gate, a third design wave and a critique pass. |
| 06:38 | Stopped the production run. |
| 06:46 | Published the source code on GitHub and saved the HQ submission fields. |
| 07:14 | Code freeze. |
| 07:35 | Private hosted copy on AWS for the jury with email-code sign-in; GitHub sign-in through Cloudflare replaced it later that day. |
| 08:58–09:32 | Built the stage opener. |
| 10:00 | Presentations. |

## From one politician to ten cities

The first plan followed the track brief literally: one public politician, an anchor website, and research goals that change the report. It worked as a pipeline. The collector read the anchor site, took the social links it publishes as the official accounts, searched Instagram and TikTok by name, and rejected same-name accounts with factual reasons. A different senator with the same name as the test subject, linked to a different town's website, was rejected; so was a government YouTube channel linked from the politician's own site, because the channel is named for the office, not the person. Extractive briefs for three goals cited different sources, and every quote matched its source text and timecode.

Two things moved me away from that plan. The election was this weekend, and the interesting question was not one national figure but the hundreds of local candidates nobody tracks. And the cost audit at 00:43 showed that broad, shallow evidence is cheap: one Instagram profile request returns a dated follower count and about twelve recent posts for $0.0023. So the scope became the ten largest city councils: Praha, Brno, Ostrava, Plzeň, Liberec, Olomouc, České Budějovice, Hradec Králové, Pardubice and Ústí nad Labem, with 5,405 valid candidacies on 127 lists.

Researching all of them was neither affordable nor useful, so one agent built a deterministic selection rule. A candidate qualifies when any single strong public signal crosses its threshold: an office or mandate, being a leading candidate of a strong party, a local vote spike in 2022, verified public reach, or reviewed public activity. Signals are not added up, so one strong signal is never diluted by missing data. When I looked at the first result I rejected one channel: being number one on a list cannot qualify a person by itself. The revised rule kept 467 candidates, at least 30 in every city, plus 62 party lists with their own evidence of relevance. [Methodology](methodology.md) has the details.

## How the agents were organised

I ran the night as a head of staff with workers, not as one long chat. The head of staff was a Claude Code agent with one job: keep my decisions, the canonical task list and the evidence straight, and drive workers toward a working demo. Workers ran in Herdr, a local terminal workspace, each in its own pane split side by side, each with its own Git worktree and a written brief. There were two worker types: one for research, prompts and reviews, one for code with headless-browser screenshots as evidence. Neither could push.

Every worker reported to a file under `docs/reports/`, and the head of staff read those files on a heartbeat. Around midnight I noticed workers sitting idle: their briefs told them to stop at each milestone and report, so they waited to be re-prompted. The rule became "workers never wait": milestone times are deadlines, not pace, reports go to files while work continues, and a question never stops work. Later I also turned off unsolicited pings to the head of staff entirely; reports and the task board were enough.

At about 00:25 the Claude head-of-staff session hit its usage limit. I moved the continuing work to Codex: a Codex profile reused the same head-of-staff instructions, workers ran GPT-6.1-Sol at extra-high reasoning on the fast tier, and two GPT-6-Astra partners worked with me on screen design and research. I kept Claude for the final screens. When it came back, Claude Opus 5.5 built the app, using parallel design agents per screen and Sonnet subagents for polish, while Sol helpers wired live data into individual screens.

The exploration agent fanned out work through subagents: 18 scouts looked at politicians' public footprint, and a 20-agent sweep collected mayors, coalitions, city accounts and programme links. The production run had one coordinator owning the budget, paid starts and all shared writes, with up to four Sol workers in panes for collection, graph building and two independent classification reviewers. Mid-run I asked for native nested subagents for bulk work instead of panes; at 04:10 a new coordinator session took over the same ledger and switched delegation to native subagents without losing a single reservation or file.

Two small tools held this together. A local control room rendered `TODO.md` as an editable Kanban with decisions, evidence and an architecture diagram, so I could see the state without reading thirty files; it is in [workspace/](../workspace/). And when the first production checkpoint passed its integrity gates, a user-level systemd timer checked readiness every two minutes and notified the app-building Claude session exactly once, then stopped itself.

Counting everything, more than twenty named workers and many more subagents ran that night. The task list kept 65 cards with full history; nothing was deleted; superseded work was archived.

## The data run

Money was handled like a production system, because agents with an API token and no ledger will spend it. Every paid run had to pin its exact input, a price snapshot, an item cap, a timeout and a provider spending cap before it started. The ledger reserved the full cap before the request, wrote a durable start boundary, made exactly one request and never retried. A run that failed after the boundary kept its reservation until it was explained. That happened once: a Google search start returned an error with no run ID, and its $0.08 stayed reserved to the end.

The exploration lane spent $2.84 in 13 Actor runs and built an Iceberg lakehouse of official data: 638,821 candidacies across 14 elections, 388,016 inferred persons with namesake flags, municipal results, and 1,054 pages of account discovery. The production run then made 56 Actor runs between 03:42 and 06:35 and settled at $91.17 in Actor charges; the ledger records $91.93 of production usage and $97.89 for the whole night, against the $120 ceiling. Exa searches, Scribe minutes and model calls were provisioned conservatively rather than priced exactly, and the subscription usage of the coding agents is not priced at all. [Apify recipes](apify-recipes.md) breaks the bill down per Actor.

At shutdown the last validated checkpoint held:

| Measure | Count |
| --- | ---: |
| Distinct social posts collected | 24,975 |
| Posts from independently verified owner accounts | 12,595 |
| Verified accounts | 110 |
| Metric observation rows | 148,150 |
| Reviewed source statements | 1,391 |
| Topics | 13 |
| Retained public web pages (unreviewed) | 347 |
| People with a source-backed photo | 306 of 467 |
| Image and video files downloaded | 28,110 (about 37 GB) |
| 2022 list results | 133 |

The difference between the first two rows is the point of the whole system. A post returned for a requested profile is not admitted until the account itself is anchored to the person by an independent source and the post's own author field matches.

## Design waves

The look went through six rounds. My first Figma concepts did not survive the evening. Two Opus workers then built competing takes around midnight, a star atlas with posts as stars and a newspaper front page, both replaying the first real collection run. At 01:25 I chose the atlas direction, and an Astra partner sketched a map-first Atlas with real Brno images. At 03:08 the five screens got their proposed names: Star Atlas, Spotlight, Pulse, Radar and Studio, and they stuck.

The first built app at 04:20 was dark, with a galaxy, glow and yellow chrome. At about 04:55 I chose the light, schematic "Atlas C" layout with a wordmark and an aperture mark reshaped into a star, and asked for real video playback and honest platform coverage. At 05:45 every screen had to pass an anti-slop gate based on the Impeccable rules: no gradient text, no decorative glow, no cards in cards, no hero-metric rows, Schibsted Grotesk and Bricolage Grotesque instead of default fonts, and one orchestrated reveal per view. A third wave at about 05:55 removed the boxy, dated feel: floating navigation, a full-bleed map with a detailed city map behind the selected town, translucent panels, portraits, party logos and 2022 results. A read-only critique at 06:24 caught low-contrast captions on translucent panels, fake single-sign-on buttons on a demo with no real login, and a banned hero-metric row; all were fixed before the freeze.

## What broke

Most problems were small and specific, and they are written up as [learnings](learnings.md). The ones that shaped the system:

- The TikTok Actor refuses spending caps below $0.50, so the skeleton's $0.12 cap made every TikTok run fail.
- Facebook and Instagram Actors return comment previews by default. Every dataset read now names the fields it wants, and production filters through an allowlist before anything touches disk.
- Instagram and TikTok media URLs expire, and Instagram blocks hotlinking. Media is downloaded at collection time with size limits and hashes.
- Anchor websites link institutional accounts. A display-name check catches them.
- In the first Facebook proof, four of five returned posts had an author different from the requested page. Facebook ownership now goes through a reviewed numeric page ID and a per-post author check.
- Two 400-post Instagram batches ran past the 900-second timeout. They kept the 6,212 posts they had delivered; the lesson is smaller batches.
- A settlement bug lost charged event counts when Apify's replies lagged. It was fixed before any reservation was recycled.
- The last attempted checkpoint was refused by its own label-source gate after the newest Facebook batch arrived, and the published pointer correctly stayed on the previous checkpoint.
- Agents waited instead of working, a local settings file made every Claude session start as head of staff, and `pkill -f starwatch` killed the agent's own shell because its working directory contained "starwatch".

## The demo

I stopped collection at 06:38. The last app export, at 06:39, used the final checkpoint. At 06:46 I published the code at [github.com/1vecera/starwatch](https://github.com/1vecera/starwatch): 526 files covering the app, pipeline, collector, workspace and eight earlier prototypes, without Git history, collected data, media, recordings or credentials. 482 tests and 264 subtests passed locally. I recorded the narration for an 89-second video around 06:30; its soundtrack was generated with ElevenLabs Music.

After the freeze I put a private copy on AWS for the jury: a private S3 bucket behind CloudFront, about 20 GB and 14,000 files. The first sign-in used Amazon Cognito email codes, until I found that Cognito's built-in sender allows only 50 emails a day per AWS account. I replaced it with Cloudflare Access and GitHub sign-in in front of the same origin.

On stage I had about ten seconds for an opener. Of three variants I chose a wall of real collected posts and videos that hands off to the Star Atlas with one click anywhere. The plan after that was to go straight into the app: Czechia, a city, a party, a person, their posts.

## What changed for the public launch

The hackathon ended at 07:14; the launch work started around noon. Starwatch is now public at [starwatch.agenticanalytics.cz](https://starwatch.agenticanalytics.cz). Code, Apify recipes, learnings and these documents are open source under the MIT licence.

- **Studio is gone.** It was meant as an evidence workspace for drafting, but it never became a clear, supported workflow, and it is unrelated to what Starwatch does well. It may come back as separate work.
- **Social sign-in only.** The welcome page is public. Everything else requires signing in with GitHub, Google or Facebook, handled by my own OAuth flow on a Cloudflare Worker. No passwords and no email codes, which also keeps load off the servers.
- **It is a snapshot.** The app says clearly that it shows public posts collected on 8–9 October 2026. It is not live monitoring, and Radar shows activity inside that snapshot, not new alerts.
- **Election silence.** Czech law bans publishing poll results from 7 October until voting ends on Saturday 10 October at 14:00. During the night an agent had collected published polls, seat projections and betting odds for the ten cities; all of that was removed from the snapshot before launch. 2026 results are added only after the polls close.
- **Data stays out of Git.** The collected snapshot is served only behind sign-in and links back to every original post. The raw scraped datasets are deleted after the launch.
- **More context.** Party programmes and news articles about candidates were added for the launch; see [collection/programs-and-articles.md](collection/programs-and-articles.md).

## What is live, cached or missing

**Live:** the website, sign-in, and the app serving the 9 October snapshot: ten cities, 127 lists, 5,405 candidacies, 110 verified accounts and 12,595 verified posts with dated metrics, 2,178 playable videos, 306 candidate photos, logos for 77 lists and 2022 results where the match is exact.

**Cached:** everything in the app is cached. Metrics were observed on 9 October between 04:49 and 06:18. The live collector and its research briefs from the first plan are in the repository but are not part of the public site.

**Missing or partial:** only 62 of the 467 qualifying candidates have a verified account with posts. Instagram and Facebook dominate; TikTok has four accounts, X five, YouTube one account and no admitted posts. 1,050 captions were never reviewed for statements, and every statement's speaker stays unknown. News and web pages collected during the night were not reviewed and are not in the verified totals. Reviewed topic labels cover 768 posts; machine labels with quoted evidence bring topic coverage to 9,309 of the 12,119 posts with text. There are no comments, no commenter data and no audience analysis, by design. [Methodology](methodology.md) lists every gap.
