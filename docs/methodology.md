# Methodology

Starwatch shows public political activity in ten Czech cities as evidence you can check. This page explains what each record means, how a social account is tied to a real candidate, what the numbers do and do not say, how topics were labelled, and where the coverage stops. The figures describe the launch snapshot, checkpoint `production-native-009`, created on 9 October 2026.

## Scope

The geography is the city councils of the ten most populous Czech municipalities on 1 January 2026 (ČSÚ): Praha, Brno, Ostrava, Plzeň, Liberec, Olomouc, České Budějovice, Hradec Králové, Pardubice and Ústí nad Labem. Their official 2026 registries list 5,409 candidacies on 127 lists; 5,405 are valid. Validity is checked per candidacy, not per person. City districts are separate councils and are not included.

## Who gets researched

Every valid candidacy stays in the data. Collection, which costs money, was focused on a smaller set chosen by a deterministic rule. A candidate qualifies when at least one independent public signal is strong enough on its own:

| Channel | Signal | Strong enough when |
| --- | --- | --- |
| O | Office or mandate | A reviewed current office, or a recorded elected mandate with a clear identity |
| M | Leading candidate of a strong party | Positions 1–3 on a list whose party or alliance had at least 10% locally in 2022, 5% nationally or 10% in the city in 2025 |
| V | Local vote spike | A top-three candidate vote total in the city in 2022, or at least 25% above the mean of the candidate's own list |
| R | Public reach | At least 10,000 followers, or followers equal to 10% of the city's population, on one independently attributed account |
| A | Public local action | A reviewed local political role plus an independent source documenting a substantive local action within the last year |

The rule takes the maximum, not the sum: one strong signal qualifies a person even when every other channel is unknown, and unknown never counts as zero. Being first on a list, now or in 2022, is kept as context but does not qualify anyone by itself. A separately reviewed public founder or leader of a local political organisation has a discovery route even without a ballot position. The result is 467 qualifying candidates, at least 30 per city, and 62 of the 127 lists qualify on their own organisational evidence.

This is a research priority, not a forecast. It says nothing about a candidate's chances, character or trustworthiness.

## The evidence model

**Area → Entity → Account → Asset → Claim → Topic**, with metric observations attached at the right level.

| Record | Meaning |
| --- | --- |
| Area | A city council. |
| Entity | A candidacy (a person on a specific list) or a party list, from the official registry. A local role is evidenced separately from any account. |
| Account | A public social account. It belongs to an entity only through an `owns_account` relation with an ownership anchor. |
| Ownership anchor | The independent evidence that an account belongs to an entity, for example the candidate's own website linking that exact handle. |
| Asset | A post, video, web page or article, with its platform and type kept separate. |
| Asset relations | `published_by` (the account that posted it), `created_by`, `about`, `depicts` and `quoted_speaker` are different relations. Only `published_by` is admitted in the snapshot. |
| Claim | A statement found in an asset, with its exact quote and, for video, a time span. A claim is a source statement, not a verified fact. |
| Topic | One of 13 policy topics a claim or post is about. |
| Metric observation | A number (followers, views, likes, comments, shares) with its platform, definition, observation time and source. |
| Quarantine | Records that failed a gate. They are kept with the reason, never silently dropped. |

Ownership, authorship, being mentioned, being pictured and being quoted are five different facts. A party account posting a photo of a candidate does not make the post the candidate's; a candidate's account posting a video does not make every voice in it the candidate's.

## Identity resolution

Three kinds of source establish three different things. The official registry establishes a candidacy: name, age, list, position, registered occupation and residence. An independent political website (the candidate's own site, the party's candidate page, a city roster) establishes that an exact account belongs to that person. The post's own author field establishes which account published it. An account is admitted only when all of the following hold: an exact independent link to the handle, a public profile that matches, and a current local candidacy or reviewed local role. A display name, bio, verified badge, search result or a scraper returning a profile is a lead, not proof.

Namesakes are expected. The registry has 5,405 valid candidacies but only inferred person keys, built from the accent-free name, an overlapping birth-year window and the registered residence; 810 valid rows carry a historical duplicate flag. These flags trigger review and never trigger a merge. Examples from the night: a former prime minister and a senator share a name and have separate Instagram accounts, separated by the website each bio links to; three candidates named Petr Hlaváček remain three people; a local party account and the national account of a party with the same name stay apart; one party's Facebook page ID was shared between city and district pages, so its scope stays unknown; an old campaign domain that now redirects to betting content was rejected as an anchor.

Facebook needed one extra step. The scraper can return posts whose author differs from the requested page, so a reviewed page address is bound to the page's numeric ID through its public metadata, and each post is admitted only when its returned author ID matches.

Accounts linked from an anchor can belong to an institution. The live collector compares each linked account's display name with the subject and rejects, for example, a government channel linked from a politician's website. Rejections state a fact about the account's relation to the anchor ("named for the office, not the person", "another website in the bio"), never a judgement about the person. Accounts that are neither accepted nor rejected stay unconfirmed and are not collected.

No face recognition is used anywhere. A candidate photo is admitted only from a source that names the person (an official candidate page, an exact-name image label) or as the avatar of an account already owned by that person, and the two are labelled differently. 306 of the 467 qualifying candidates have such a photo; the rest show initials.

## Linking to the 2022 election

In the snapshot, a 2026 candidacy shows a 2022 municipal result only when the name matches exactly in the same city, the birth windows derived from the official ages at both elections overlap, and the match is unique in both directions; 1,912 candidacies have one. The backend's stricter link table also requires the same registered residence and a shared specific party code (1,341 links), and every link is labelled as not independently resolved. A 2026 list shows a 2022 list result only when the city, the official party or alliance code and the coalition composition are all unchanged; 43 lists qualify and 84 stay unknown. Ballot numbers and member overlap are never used to transfer a result.

Municipal candidate vote totals in the Czech system include votes cast for the whole list. They are shown as official totals, not as personal preference votes.

## Metrics are dated observations

- Every number has a platform, a definition, an observation time and a source. Followers belong to accounts; views, likes, comments and shares belong to posts.
- A provider value of `-1` and other invalid values become unknown with a recorded reason. Unknown is shown as a dash, never as zero.
- When a post was observed more than once, the newest observation is used. Identical same-time observations are deduplicated; conflicting ones become unknown.
- Where a single reach number is needed, it is views if the platform reports them, otherwise likes plus comments. The label says which.
- Metrics in the snapshot were observed on 9 October 2026 between 04:49 and 06:18 CEST. Follower counts are global counts at that moment, not local residents or voters.
- A recent-posts sample does not cover a full time window. Comparisons state their window and what they cover.
- Engagement is attention, not support. A popular critical post says nothing about support for its subject.

## Topic labelling

Topics come from post captions. The taxonomy has 13 labels: housing, transport, environment, public space, public finance, education, health and social, governance, safety, culture and sport, economy and work, election process, and other.

Captions were bundled into fixed classification packets with the source text, its hash and the owner. A model worker (Codex, GPT-6.1-Sol) proposed topics and claims, each claim with an exact quote whose Unicode code-point offsets must match the source. A second, independently registered worker reviewed each packet. Findings of wrong owner, wrong identity, unsupported quote or unsupported speaker block promotion. Only labels that are current, accepted and bound to the exact source hash reach the snapshot; corrections must reference the exact label they replace. The speaker of every claim stays unknown, because a caption on a candidate's account is not proof the candidate said it.

The final review bundle covered 950 captions and 2,238 proposed claims: 851 captions accepted, 99 held. In the snapshot, 1,391 reviewed source statements sit on 786 posts and 768 posts carry at least one topic. For the launch, the remaining posts with text received machine labels: 0–3 topics per post from Claude on AWS Bedrock, each backed by a phrase quoted verbatim from the post, never overriding a reviewed label and marked as machine labels in the app. Together, 9,309 posts carry a topic. Machine labels can be wrong; [collection/topic-labels.md](collection/topic-labels.md) has the method and the agreement with the reviewed sample. Related topics describe co-occurrence, not causation.

## Coverage

| City | Valid candidacies | Qualifying | Relevant lists | Verified person accounts | Verified list accounts | Verified posts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Praha | 1,059 | 61 | 7 | 22 | 4 | 3,708 |
| Brno | 828 | 54 | 6 | 17 | 4 | 2,592 |
| Ostrava | 715 | 55 | 7 | 4 | 4 | 1,013 |
| Plzeň | 549 | 58 | 8 | 7 | 1 | 1,371 |
| Liberec | 361 | 32 | 5 | 5 | 2 | 705 |
| Olomouc | 472 | 47 | 6 | 5 | 2 | 684 |
| České Budějovice | 405 | 51 | 7 | 5 | 1 | 387 |
| Hradec Králové | 369 | 43 | 6 | 6 | 1 | 654 |
| Pardubice | 351 | 36 | 6 | 12 | 3 | 1,123 |
| Ústí nad Labem | 296 | 30 | 4 | 3 | 2 | 358 |
| **Total** | **5,405** | **467** | **62** | **86** | **24** | **12,595** |

| Platform | Verified accounts | Verified posts | Playable videos |
| --- | ---: | ---: | ---: |
| Instagram | 69 | 9,157 | 2,178 |
| Facebook | 31 | 2,567 | 0 |
| TikTok | 4 | 598 | 0 |
| X | 5 | 273 | 0 |
| YouTube | 1 | 0 | 0 |

Known gaps:

- Only 62 of the 467 qualifying candidates have a verified account with posts. For the rest, accounts were either not found, not independently anchored, or private. Absence in Starwatch is not absence online.
- Posts were published between 2017 and 9 October 2026; 7,300 of them since 9 April 2026. History depth differs by account and platform, because collection asked for a bounded number of latest posts per account (up to 400) rather than a fixed date range.
- YouTube videos were collected for three channels but not admitted, because the channel-ownership review was not finished.
- Web pages and news collected during the night (347 retained texts) were not reviewed for publisher, subject or speaker and are excluded from verified totals. Articles added for the launch store only title, outlet, date, URL and how the match was made.
- Statements come from captions only. Spoken words in videos were transcribed for a few early test videos but are not part of the snapshot.
- 2026 results are not included until voting ends.

## What Starwatch never claims

- That a statement is true. A claim is what a source says.
- Who said a quote, unless that is separately evidenced. In the snapshot the speaker is always unknown.
- That likes, views or followers measure support, voting intention or electoral success.
- That a missing account, post or metric means the person has none.
- Anything about a person's character, trustworthiness, beliefs or sensitive traits.
- Anything about voters or commenters. No comments, commenter identities, likers or follower lists are collected.
- That the snapshot is live. It shows public posts collected on 8–9 October 2026.
- Who will win. No polls, forecasts or betting odds are shown.
