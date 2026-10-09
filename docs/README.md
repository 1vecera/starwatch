# Starwatch documentation

Starwatch shows what candidates in the ten largest Czech cities publish in public, who gets attention and where every number comes from. It is live at [starwatch.agenticanalytics.cz](https://starwatch.agenticanalytics.cz) as a snapshot of public posts collected on 8–9 October 2026. It was built in one night at the Agents 0.0.7 hackathon in Prague by Daniel Večeřa. Code, recipes and documents are MIT-licensed.

## Start here

| Document | Read it for |
| --- | --- |
| [The story](story.md) | How Starwatch was built in one night: decisions with times, the agent setup, the data run, what broke, the demo and the launch |
| [Methodology](methodology.md) | The evidence model, identity resolution, what the metrics mean, topic labelling, coverage and gaps, and what Starwatch never claims |
| [Architecture](architecture.md) | Collection pipeline, lakehouse, evidence graph, export, static app, hosting and sign-in |

## Reuse it

| Document | Read it for |
| --- | --- |
| [Apify recipes](apify-recipes.md) | Every Apify Actor used, with exact inputs, kept fields, costs, run times, failure modes and fixes |
| [recipes/apify/](../recipes/apify/) | The runnable Actor inputs |
| [Learnings](learnings.md) | Practical lessons on scraping, identity, cost control, agent orchestration, design and hosting |
| [Data sources](data-sources.md) | Every source, what it contributes, when it was observed and its terms |
| [Programmes and articles](collection/programs-and-articles.md) | How party programmes and news articles were found and matched for the launch |
| [Topic labels](collection/topic-labels.md) | How machine topic labels were added for unreviewed posts, and how well they agree with the reviewed sample |

## Responsibility

| Document | Read it for |
| --- | --- |
| [Privacy and ethics](privacy-and-ethics.md) | Public sources only, no voter profiling, election silence, retention, and how candidates request corrections |

## Component READMEs

- [pipeline/README.md](../pipeline/README.md): running collection, building checkpoints and the local read API.
- [app/tools/RAW_FORMAT.md](../app/tools/RAW_FORMAT.md): the snapshot format the app reads.
- [collector/README.md](../collector/README.md): the first-plan live research engine.

Questions and corrections go to [GitHub issues](https://github.com/1vecera/starwatch/issues). Daniel Večeřa, Prague: [LinkedIn](https://www.linkedin.com/in/1vecera/) and [X](https://x.com/1vecera).
