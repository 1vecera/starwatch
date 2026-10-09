# Machine topic labels

The reviewed topic labels in the snapshot cover 786 of 12,595 posts, so the topic mix had little to show. For the launch, Starwatch adds an optional file next to the snapshot, `topic-labels.js`, with machine topic labels for the posts nobody reviewed. Each label names one of the snapshot's 13 topics and quotes the words in the post that support it. Machine labels can be wrong; reviewed labels win.

The code is [`czlake.topic_machine`](../../pipeline/src/czlake/topic_machine.py), with tests in [`pipeline/tests/test_topic_machine.py`](../../pipeline/tests/test_topic_machine.py).

## What a label means

A topic label says what a post is about: its subject, as written in the post's own text. It says nothing about the author's stance, the tone, whether a claim is true, or what kind of person wrote it. A post praising a new tram line and a post attacking it are both `transport`. The labels infer no sensitive traits and contain no polls, forecasts or estimates of support.

Every machine label carries an evidence phrase of at most 12 words copied from the post. The phrase shows why the topic was given; it does not prove the label is right.

The app shows machine labels separately from reviewed ones. A post with a reviewed label (or a reviewed decision to give it none) is never relabelled.

## Topics

The taxonomy is the reviewed `production-labels-v1` set; topic IDs in the app are `production-labels-v1:<topic>`. The definitions below are the ones the model sees and the ones in the overlay.

| Topic | Definition |
| --- | --- |
| `housing` | Flats and houses, rents, municipal and affordable housing, new residential construction and housing-development areas. |
| `transport` | Public transport (trams, buses, trolleybuses, trains, stations), roads, traffic, parking, closures and detours, cycling and walking routes. |
| `environment` | Trees and greenery, climate and heat, air, noise, water and sewerage, waste, nature and animals. |
| `public_space` | Squares, streets, parks, playgrounds, pavements, lighting, cleanliness, urban planning, architecture and the look of neighbourhoods. |
| `public_finance` | The city budget, local taxes and fees, debt, the cost of investments, grants and subsidies, public procurement and the use of public money. |
| `education` | Nurseries, kindergartens, primary and secondary schools, school capacity and buildings, teachers, universities and science. |
| `health_social` | Hospitals, doctors, emergency care, social services, seniors, disability, families in need, addiction and homelessness. |
| `governance` | How the city, region and state are run: councils, mayors, government and parliament, parties, coalitions and opposition, office holders, laws, transparency, corruption and citizen participation. |
| `safety` | Police and municipal police, crime, public order, camera systems, firefighters, crisis management, road safety, and national security and defence. |
| `culture_sport` | Cultural venues and events, festivals, theatres, music, museums, history, heritage and monuments, sport clubs, matches and facilities, leisure events. |
| `economy_work` | Jobs and wages, businesses and industry, the local economy, tourism, prices, cost of living and energy prices. |
| `election_process` | The election and campaign itself: dates and voting, calls to vote, how to fill in the ballot, candidacies and candidate lists, campaign events, debates and results. |
| `other` | Clearly political or campaign content with no issue from the twelve topics above, such as a general slogan or a campaign launch. |

## How it works

1. **Select.** Every post with text and no reviewed label: 11,333 posts with 10,803 distinct texts. Identical captions (the same post on Facebook and Instagram) are sent once; the evidence check still runs on each post's own text.
2. **Read.** The model sees the caption only, up to 2,000 characters, hashtags included. Images, video, linked pages and comments are not read.
3. **Label.** Claude on Amazon Bedrock (`eu-central-1`, temperature 0) gets up to 25 posts (14,000 characters) per request with the definitions, Czech cue words, seven rules and 25 invented example posts, and answers in a strict JSON schema: per post, zero to three topics, the most central first, each with an evidence phrase. The rules say to label subject matter only, to label personal posts by their subject (a hockey match is `culture_sport`), to leave greetings, thanks and bare links unlabelled, and to use `other` only for campaign-generic content.
4. **Check.** A topic is kept only if its evidence phrase occurs in the post after Unicode NFC, case folding and whitespace collapsing. The stored phrase is the post's own wording, cut to 12 words. Unknown topics, repeated topics and topics beyond the third are dropped, and `other` is dropped when the post also has a specific topic.
5. **Cache.** Each answer is stored with the asset ID and the SHA-256 of the text, so a rerun makes no calls and a changed caption is asked again. Every call is written to a ledger with its token counts and cost, and a call that could push the ledger over the budget is not made.
6. **Export.** The overlay is written from the cache without model calls.

### Two models

Claude Sonnet 4.6 labels better than Claude Haiku 4.5 (see validation), but Sonnet for all 10,803 texts would have cost about $15.40, over the $15 budget for this task. Sonnet labelled posts published since 1 June 2026, newest first, until its share of the budget ran out among posts from 5 June; Haiku labelled the rest. Every post published after 5 June 2026 was read by Sonnet, and older posts whose caption also appears in a newer post reuse that answer: 5,530 posts by Sonnet, 5,803 by Haiku. Haiku is almost as precise but gives fewer labels per post, so older posts are under-labelled, mainly for governance, public finance, safety and economy. Each label records which model made it.

## Run it

From `pipeline/`, with the Bedrock credentials in `DAS_ITEM_AWS_BEDROCK__AWS_ACCESS_KEY_ID`, `DAS_ITEM_AWS_BEDROCK__AWS_SECRET_ACCESS_KEY` and optionally `DAS_ITEM_AWS_BEDROCK__AWS_REGION`:

```bash
tm() { uv run --with "anthropic[bedrock]>=1.11" python -m czlake.topic_machine \
         --snapshot ../app/web/data/real.js --work ../tmp/topics "$@"; }
tm --model sonnet validate                                   # label the reviewed posts and compare
tm --model haiku validate
tm --model sonnet --budget 10.8 label --since 2026-06-01     # newest first, stops at the ledger cap
tm --model haiku --budget 14.8 --workers 2 label --unanswered-by sonnet   # the rest
tm export --models sonnet,haiku --out ../app/web/data/topic-labels.js
tm spend                                                     # tokens and cost per model
```

`--budget` caps the whole ledger in US dollars, not one run. A batch that fails (for example on Bedrock throttling after the SDK's retries) is logged and its posts are asked again on the next run; six parallel Haiku workers hit throttling once, two did not. The cache and ledger live in the ignored `tmp/topics/`; the overlay lives in the ignored `app/web/data/`.

## Output

```js
window.SW_TOPIC_LABELS = {
  generated_at: "ISO-8601", model: "model IDs used", method: "one paragraph",
  models: { sonnet: { model, name, prompt, posts, labelled, published: [first, last] }, haiku: { … } },
  taxonomy: { "production-labels-v1:housing": "Housing: …", … },
  validation: { sonnet: { … }, haiku: { … } },     // agreement with the reviewed labels, below
  coverage: { eligible, answered, labelled, per_topic, dropped, spend },
  labels: { "<asset id>": { topics: ["production-labels-v1:transport", …],
                            evidence: { "production-labels-v1:transport": "Šalina na Lesnou" },
                            model: "sonnet" } }
};
```

Only posts with at least one topic appear in `labels`.

## Validation

Both models labelled the 786 posts that have reviewed labels, and their labels were compared with the reviewed ones. These posts are not in the overlay.

| Measure | Claude Sonnet 4.6 | Claude Haiku 4.5 |
| --- | ---: | ---: |
| Posts compared | 786 | 786 |
| Posts with any label (reviewed: 768) | 654 | 586 |
| Precision, all topics | 0.89 | 0.90 |
| Recall, all topics | 0.64 | 0.45 |
| Precision without `other` | 0.90 | 0.92 |
| Recall without `other` | 0.69 | 0.49 |
| F1 without `other` | 0.78 | 0.64 |
| Recall within three | 0.71 | 0.50 |
| Macro F1 (13 topics) | 0.72 | 0.58 |
| First machine topic is a reviewed topic | 0.92 | 0.91 |
| Exact same topic set | 0.44 | 0.29 |
| Mean Jaccard overlap | 0.62 | 0.48 |

| Topic | Reviewed | Sonnet 4.6 labels / P / R / kappa | Haiku 4.5 labels / P / R / kappa |
| --- | ---: | ---: | ---: |
| `housing` | 34 | 30 / 0.93 / 0.82 / 0.87 | 26 / 0.96 / 0.74 / 0.83 |
| `transport` | 103 | 96 / 0.96 / 0.89 / 0.91 | 67 / 1.00 / 0.65 / 0.76 |
| `environment` | 43 | 36 / 0.89 / 0.74 / 0.80 | 28 / 0.93 / 0.60 / 0.72 |
| `public_space` | 89 | 68 / 0.91 / 0.70 / 0.77 | 66 / 0.83 / 0.62 / 0.68 |
| `public_finance` | 88 | 77 / 0.90 / 0.78 / 0.82 | 34 / 0.91 / 0.35 / 0.48 |
| `education` | 42 | 27 / 0.89 / 0.57 / 0.68 | 16 / 1.00 / 0.38 / 0.54 |
| `health_social` | 61 | 36 / 0.97 / 0.57 / 0.70 | 26 / 1.00 / 0.43 / 0.58 |
| `governance` | 372 | 260 / 0.91 / 0.64 / 0.59 | 145 / 0.93 / 0.36 / 0.35 |
| `safety` | 82 | 47 / 1.00 / 0.57 / 0.71 | 25 / 0.96 / 0.29 / 0.42 |
| `culture_sport` | 170 | 101 / 0.98 / 0.58 / 0.68 | 75 / 0.99 / 0.44 / 0.54 |
| `economy_work` | 51 | 26 / 0.92 / 0.47 / 0.61 | 20 / 0.75 / 0.29 / 0.40 |
| `election_process` | 212 | 238 / 0.78 / 0.88 / 0.76 | 190 / 0.86 / 0.77 / 0.75 |
| `other` | 115 | 11 / 0.55 / 0.05 / 0.07 | 13 / 0.15 / 0.02 / 0.00 |

How to read it:

- Precision is the share of machine labels the reviewers also gave; recall is the share of reviewed labels the machine found. Kappa corrects per-topic agreement for chance.
- Reviewers could give up to nine topics per post; the machine gives at most three. "Recall within three" divides by the reviewed labels a three-topic answer could reach.
- Reviewers used `other` as a catch-all for posts without a public issue, including personal posts and emoji. The machine leaves those unlabelled unless they are campaign-generic, so agreement on `other` is near zero by design. The figures without `other` describe the twelve real topics.
- The prompt was tuned in three rounds against these same 786 posts (definitions, rules and invented examples; no reviewed post was copied into the prompt), so the numbers are somewhat optimistic for unseen posts.

## Coverage

| | Before | After |
| --- | ---: | ---: |
| Posts with at least one topic | 768 (6 % of 12,119 posts with text) | 9,309 (77 %) |
| Reviewed posts | 786 | 786, unchanged |
| Machine-labelled posts | – | 8,541 of 11,333 eligible (Sonnet 4,756 of 5,530, Haiku 3,785 of 5,803) |
| Topic labels | 1,462 reviewed | 1,462 reviewed + 12,944 machine |

The models gave no topic to 2,792 eligible posts: mostly greetings, thanks, personal posts and bare links, plus posts on which Haiku missed a topic. 476 posts have no text at all. Of the topics the models proposed, 279 were dropped because the evidence phrase was not in the post, 108 as repeats and 6 because `other` came with a specific topic.

| Topic | Reviewed | Machine (Sonnet) | Machine (Haiku) | Total |
| --- | ---: | ---: | ---: | ---: |
| `housing` | 34 | 376 | 248 | 658 |
| `transport` | 103 | 841 | 581 | 1,525 |
| `environment` | 43 | 539 | 417 | 999 |
| `public_space` | 89 | 719 | 754 | 1,562 |
| `public_finance` | 88 | 502 | 224 | 814 |
| `education` | 42 | 283 | 219 | 544 |
| `health_social` | 61 | 596 | 284 | 941 |
| `governance` | 372 | 1,412 | 715 | 2,499 |
| `safety` | 82 | 349 | 187 | 618 |
| `culture_sport` | 170 | 938 | 653 | 1,761 |
| `economy_work` | 51 | 203 | 135 | 389 |
| `election_process` | 212 | 1,325 | 345 | 1,882 |
| `other` | 115 | 69 | 30 | 214 |

## Cost

All calls ran on 9 October 2026 through the EU cross-region inference profiles in `eu-central-1`, priced at list price plus 10 %: Sonnet 4.6 $3.30 in / $16.50 out, Haiku 4.5 $1.10 / $5.50 per million tokens. Sonnet read the 3,508-token instructions from the prompt cache at a tenth of the input price; Haiku's instructions are below its 4,096-token cache minimum.

| Step | Model | Calls | Posts | Input tokens | Cached input (read + written) | Output tokens | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Validation, prompt 1 | Haiku 4.5 | 30 | 745 | 153,775 | 0 | 18,505 | $0.27 |
| Validation, prompt 2 | Haiku 4.5 | 30 | 745 | 155,875 | 0 | 21,316 | $0.29 |
| Validation, prompt 2 | Sonnet 4.6 | 30 | 745 | 155,905 | 0 | 32,012 | $1.04 |
| Validation, final prompt | Haiku 4.5 | 30 | 745 | 202,855 | 0 | 23,508 | $0.35 |
| Validation, final prompt | Sonnet 4.6 | 30 | 745 | 97,645 | 105,240 | 29,735 | $0.93 |
| Labelling | Sonnet 4.6 | 209 | 5,106 | 1,064,438 | 733,172 | 224,986 | $7.47 |
| Labelling | Haiku 4.5 | 230 | 5,656 | 1,879,410 | 0 | 165,923 | $2.98 |
| **Total** | | **589** | | **3,709,903** | **838,412** | **515,985** | **$13.33** |

Validation sends 745 distinct texts for the 786 reviewed posts. Haiku's labelling ran twice: the first run, with six workers, lost 13 calls to throttling (not charged); the second, with two workers, sent the 324 texts those calls had held. A rerun of every command above costs nothing, because all answers are cached.

## Limits

- Machine labels can be wrong; reviewed labels win. No person checked them.
- Captions only. A video about schools with the caption "Díky!" gets no label.
- At most three topics per post; long programme posts lose secondary topics.
- Two models: posts published before 5 June 2026 were mostly read by Haiku, which finds fewer topics. On the reviewed posts it found 49 % of the reviewed labels against Sonnet's 69 % (without `other`); in the labelling it gave a topic to 65 % of its posts against Sonnet's 86 %, partly because older posts are more often personal. Topic shares for older periods understate secondary topics, mostly governance, public finance, safety and economy.
- The evidence phrase shows the topic is mentioned, not that it is central or that the label is correct.
- `other` means campaign-generic here; in the reviewed labels it also covers personal posts.
- The labels describe subject matter only: no stance, sentiment, character, truth, sensitive traits, polls or forecasts.
