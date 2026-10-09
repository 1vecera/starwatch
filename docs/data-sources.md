# Data sources

Every record in Starwatch keeps the URL it came from and when it was fetched. This page lists the sources, what Starwatch takes from each, when it was observed, and the terms that apply. Political content comes only from public sources about public candidates. Nothing comes from private groups, private messages, logged-in-only pages, leaked material or fake accounts.

## Official data

| Source | What Starwatch uses | Observed | Terms |
| --- | --- | --- | --- |
| [Election open data, Czech Statistical Office](https://volby.gov.cz/opendata/) | The 2026 municipal candidate registry ([KV2026reg20261007](https://volby.gov.cz/opendata/kv2026/KV2026reg20261007_csv.zip), published 7 October 2026): every candidacy with name, age, occupation, residence, list and position. 2022 municipal registries and results for the 2022 history. Registries and results of municipal (2018, 2022), Chamber (2021, 2025), regional (2020, 2024), Senate (2020–2026), European (2019, 2024) and presidential (2023) elections in the lakehouse, used for research selection. | Fetched 8 October 2026, 23:50 | Official open data published by ČSÚ; attribute ČSÚ |
| [ČSÚ population, OBY02A](https://data.csu.gov.cz/datastat/data/VYBER/OBY02AT02) | Population of every municipality on 1 January 2026, used to choose the ten largest cities | Fetched 8 October 2026 | Official open data published by ČSÚ |
| [Chamber of Deputies open data, poslanci.zip](https://www.psp.cz/eknih/cdrom/opendata/poslanci.zip) | Members of parliament, as context for office signals | Fetched 8 October 2026, 23:57 | Official open data |
| City council rosters and official candidate pages | Local roles and exact links from a candidate's page to their social accounts | 8–9 October 2026, bounded direct requests | Public web pages; only links and short facts are kept |

## Social platforms, collected through Apify

All platform data was collected through Apify Actors from public profiles and public posts; [Apify recipes](apify-recipes.md) has the exact inputs. Only allowlisted metadata is kept: post ID, URL, time, caption or text, media links, author fields and public counts. Comments, commenter and liker identities, follower lists, tagged users and private profiles are never collected.

| Platform | What Starwatch uses | Observed |
| --- | --- | --- |
| Instagram | Profile metadata (public or private, follower count, bio links) and posts of verified accounts, with images and videos | 8–9 October 2026 |
| Facebook | Posts of verified pages and profiles, with images and public reaction, comment and share counts | 9 October 2026 |
| TikTok | Videos and public counts of verified accounts; TikTok's own Czech caption tracks for early test videos | 8–9 October 2026 |
| X | Media posts of verified accounts, excluding replies and reposts | 9 October 2026 |
| YouTube | Video metadata of channels linked from candidates' websites (collected, not admitted to the snapshot) | 9 October 2026 |
| Google search results | Leads for official websites, social accounts, portrait sources and news. A search result is never treated as proof. | 8–9 October 2026 |

Posts remain the work of their authors. Starwatch shows them behind sign-in for research and commentary, attributes them to the publishing account and links every post to its original. Media is served from the snapshot because the platforms' own media links expire.

## Reference and enrichment

| Source | What Starwatch uses | Terms |
| --- | --- | --- |
| [Wikidata](https://query.wikidata.org/) | Published social handles, websites and party company IDs (IČO) of Czech politicians and parties, used only as dated leads for identity review | CC0 |
| [Wikimedia Commons](https://commons.wikimedia.org/) | National party logos, each with its file page and licence recorded (public domain, CC BY-SA 3.0 or 4.0) | Per file |
| Official party and candidate websites | Programme pages, candidate portraits that name the person, logos of local lists | Public web pages; source URL kept with each item |
| [Exa](https://exa.ai/) | Search for official pages, programmes and news articles during the source audit and the launch research | Search API; only the found URLs and short facts are kept |
| [ElevenLabs Scribe v2](https://elevenlabs.io/docs/api-reference/speech-to-text) | Czech transcripts of three short test videos in the first-plan collector (2.6 minutes). Not used in the public snapshot. | Paid API |

## Party programmes and news articles

For the launch, party programmes and news articles about candidates were added as separate optional files. Programme entries keep the programme URL and short verbatim excerpts with a machine-written summary that the app labels as such. Article entries keep only title, outlet, date, URL and how the match to a candidate or list was made; article bodies are never stored. The collection method and coverage are documented in [collection/programs-and-articles.md](collection/programs-and-articles.md).

## Maps

| Source | Use | Terms |
| --- | --- | --- |
| [ČÚZK](https://cuzk.gov.cz/) administrative boundaries, via [siwekm/czech-geojson](https://github.com/siwekm/czech-geojson) | Region, national and city-council boundaries, simplified and bundled in `app/web/geo/` | ČÚZK open data; attributed on the map |
| [OpenFreeMap](https://openfreemap.org/) | Online base map tiles (OpenStreetMap data) | OpenStreetMap contributors, ODbL; the app falls back to the bundled boundaries offline |

## What is deliberately not a source

- Opinion polls, seat projections and betting odds. Some were collected during the night; all were removed before launch because of the pre-election publication ban, and none will be added.
- Comments and reactions by individual people, follower lists and any audience or voter data.
- Face recognition or any other biometric matching.
- Private, closed or login-only groups and pages, and anything requiring a CAPTCHA bypass.
