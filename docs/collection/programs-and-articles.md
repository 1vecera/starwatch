# Programmes and articles

For the launch, Starwatch adds two optional files next to the snapshot: `programs.js` with each list's own 2026 election programme, a machine-written one-sentence summary and up to eight promises, and `articles.js` with Czech news articles that name a list or one of its leading candidates. This page is the recipe: what is collected and why, how to run it, what it cost and where it fails.

The code is the `czlake.campaign` package in [pipeline/src/czlake/campaign/](../../pipeline/src/czlake/campaign/), with tests in `pipeline/tests/test_campaign_*.py`.

## Why

The snapshot shows what candidates post. Programmes add what the lists promise in writing, and articles add how the press covered them during the campaign. Both stay close to the sources: every promise carries a Czech quote that was found verbatim in the programme text, and every article is a link with its title, outlet and date.

## What is collected

| File | Per item | Never stored |
| --- | --- | --- |
| `programs.js` (`window.SW_PROGRAMS`) | Status (`found`, `not_found`, `unreachable`), programme URL and title, format (`html` or `pdf`), fetch time, one neutral summary sentence and the model that wrote it, up to eight promises (English paraphrase, Czech quote of at most 300 characters, topic, source URL with `#page=N` for PDFs), every source page used, when the search ran and, for lists without a programme, a note saying why | Programme text, commentary by third parties |
| `articles.js` (`window.SW_ARTICLES`) | Title, outlet, publication date, URL, city (plus every city matched), matched lists and candidates, whether the match is in the title or the search highlight, the matched names, and when it was observed | Article bodies, highlights, comments, authors |

Only programmes published by the list itself or its party count: the list's website, its programme page or PDF, or the party's page for that city. News coverage of a programme, aggregators such as programme comparison sites, city-district programmes, earlier elections and national programmes that are not specific to the city are rejected. Polls, seat projections and betting odds are excluded everywhere, in line with the election-silence rule and the project's scope.

## How it works

### Programmes

1. **Discover.** Two [Exa](https://exa.ai/) searches per list: `volební program <list> <city> komunální volby 2026`, and the list's brand with its lead candidate and city. Social networks, news outlets, city halls, registries and third-party programme guides are dropped; the best eight URLs remain.
2. **Fetch.** A plain HTTP GET of each candidate (free), with an identifying user agent. Links on those pages whose text or path looks like a programme (`program`, `priority`, `100 kroků`, PDFs) are added, up to sixteen candidates per list. Identical texts reached under different URLs are kept once.
3. **Render.** Candidates that look like a programme but give almost no text over HTTP are rendered by one batched [Apify Website Content Crawler](https://apify.com/apify/website-content-crawler) run (`playwright:adaptive`, depth 0).
4. **Extract text.** HTML through [trafilatura](https://trafilatura.readthedocs.io/) main-text extraction, falling back to all visible text when the main-text pass is thin; PDFs through [pypdf](https://pypdf.readthedocs.io/), one text per page, with words hyphenated across line breaks joined.
5. **Triage.** Claude Haiku 4.5 on Amazon Bedrock sees each candidate's URL, title and first 1,200 characters and picks up to three documents that are this list's programme for this city. Picks from a second publisher are dropped.
6. **Check ownership.** Before any extraction, the chosen pages must name the city or a leading candidate (a generic party text does not), and must point to this list: its candidates, its brand or abbreviation (in the text or the host name) or its parties. If two lists in one city end up with the same page, the list the page points to more strongly keeps it.
7. **Extract promises.** Claude Sonnet 4.6 on Amazon Bedrock reads the chosen documents (up to 90,000 characters in total) and returns whether they really are the programme, its title, one neutral English summary sentence and up to ten concrete, city-wide commitments, each with a Czech quote copied from the document, a paraphrase of that quote only, and one of the snapshot's 13 topics. Requests use JSON-schema outputs.
8. **Verify quotes.** Each quote must occur in the extracted text after folding whitespace, soft hyphens and typographic quote and dash variants. The stored quote is the source's own characters with whitespace collapsed, never the model's spelling. Quotes that are not found, are longer than 300 characters or repeat an earlier one are dropped; the first eight that pass are kept. For PDFs the page that contains the quote becomes `#page=N`.
9. **Search again.** Lists without a programme get a second pass with two more searches (the brand with the city, and the list's priorities for the city), then a third pass restricted to party-wide sites, that is party-named domains that host the same party's programmes in at least two cities (in this run `anobudelip.cz` for ANO, `pirati.cz`, `starostove.cz` and `svobodni.cz`).

A list is `found` when a programme passed the triage, the ownership checks and the extraction check; `unreachable` when a search result that names the list and looks like its 2026 programme could not be read even after rendering; and `not_found` otherwise, with a `note` saying why. The summary and paraphrases are machine-written and the app labels them as such; the Czech quote and the link are the evidence.

### Articles

1. **Search.** Exa news search restricted to 1 September to 9 October 2026, with two queries per city (`komunální volby <city> 2026` and a query for mayoral candidates) and two per list (its brand or name with the city, and its lead candidate with the city). Exa returns titles, dates and two short highlights per result; the full text is never requested.
2. **Filter.** Czech (`.cz`) outlets only. Dropped: social networks; party, list and candidate websites (including programme domains and domains spelled like a list brand or a candidate's name); city halls; press-release wires; aggregators that republish other outlets; tag, author and profile pages; undated results and anything outside the window. Polls, election models, voter preferences, betting, and titles that forecast or report results are dropped. A date written in the URL wins over the search index's date, which is occasionally wrong.
3. **Match.** An article is kept when its title or highlights name, together with the city:
   - one of a list's top five candidates by exact full name (first name then surname, capitalised as written, in any Czech grammatical case: "Tomáš Hrubý", "Tomáše Hrubého", "s Tomášem Hrubým"); a name found only in the highlights also needs political context (elections, council, mayor, party, campaign); or
   - a list's own brand ("PRAHA SOBĚ", "Ostravak", "srdcOVA") with political context; or
   - in the title, the name of a party that has exactly one list in that city, with political context.

   The city requirement (any case or the residents' adjective, e.g. "v Brně", "brněnský") guards against namesakes. A surname alone never matches.
4. **Deduplicate.** URLs are normalised (consent wrappers and tracking parameters removed), and syndicated copies with the same title are kept once.

## How to run it

Credentials come from the environment only: `EXA_API_KEY`, `APIFY_TOKEN`, and AWS credentials for Bedrock (the standard chain, or `<prefix>AWS_ACCESS_KEY_ID` and `<prefix>AWS_SECRET_ACCESS_KEY` with `--aws-env-prefix <prefix>`). Nothing secret is written to the cache or logs.

```bash
cd pipeline
uv sync
CACHE=../tmp/campaign          # ignored by Git; raw responses, fetched pages, spend ledger
SNAPSHOT=../app/web/data/real.js

# Programmes for all lists (--lists relevant for the 62 relevant ones; --merge keeps earlier entries)
uv run python -m czlake.campaign --snapshot $SNAPSHOT --cache $CACHE \
  programs --lists all --out ../app/web/data/programs.js

# Articles for all lists; programme domains are excluded from news results
uv run python -m czlake.campaign --snapshot $SNAPSHOT --cache $CACHE \
  articles --lists all --programs ../app/web/data/programs.js --out ../app/web/data/articles.js

# Spend recorded so far, and an offline rebuild that calls no service
uv run python -m czlake.campaign --cache $CACHE spend
uv run python -m czlake.campaign --snapshot $SNAPSHOT --cache $CACHE --offline \
  programs --lists all --out ../app/web/data/programs.js
```

Every response (searches, HTTP bodies, renders, model answers) is cached before use, so an interrupted run resumes where it stopped and `--offline` rebuilds byte-identical files from the cache. `generated_at` is the latest provenance time in the data, not the wall clock. Hard spend caps (`--max-exa-usd`, `--max-bedrock-usd`, `--max-apify-usd`, default $10, $20 and $15) are checked before every paid call against a ledger that accumulates across runs sharing the cache. `--ids` processes explicit list ids, `--no-render` never calls Apify, and `--triage-model` and `--extract-model` choose other Bedrock models (add their prices to `PRICES` in `llm.py` first).

Run the tests with `uv run pytest tests/test_campaign_*.py`.

## Results and costs (9 October 2026)

Collected on 9 October 2026 for the snapshot's 10 cities and 127 lists (62 of them in the snapshot's relevant set).

| | Relevant lists | Other lists | All |
| --- | --- | --- | --- |
| Programme found | 41 | 33 | 74 |
| Not found | 21 | 32 | 53 |
| Promises kept | 313 | 249 | 562 |

- Found programmes: 66 web pages read over HTTP, 2 web pages rendered by Apify, 6 PDFs. 67 lists were found in the first pass; the deeper second pass and the party-site pass added the rest.
- Quote check: the extraction model proposed 701 promises for the found programmes. 41 (5.8%) were dropped because their quote was not found verbatim in the fetched text, 5 because the quote was longer than 300 characters and 93 because a list already had eight. 562 were kept.
- Why lists are `not_found`: for 32 the triage found no candidate page that is the list's own city programme; for 9 the extraction model rejected the chosen page (news coverage, a candidate list, a national landing page); 8 chosen pages named neither the city nor a leading candidate (generic party texts such as the national Motoristé sobě page); 3 named neither the list, its parties nor its candidates; 1 was another list's programme in the same city. Typical causes are lists that only have a national campaign page, programmes published only as images or social posts, and search surfacing news about a programme rather than the programme.
- Articles: 274 news searches returned 1,359 unique URLs; 409 articles were kept (190 matched in the title, 219 in the highlights). They cover 122 lists, including all 62 relevant ones, and 183 candidates. Dropped: 428 not Czech news or not an article page, 53 poll, forecast or result coverage, 447 without a name and city match, 21 syndicated duplicates, 1 undated.

| Service | Use | Calls | Cost |
| --- | --- | --- | --- |
| Exa | Programme discovery and news search | 662 searches | $4.93 |
| Amazon Bedrock, Claude Haiku 4.5 | Candidate triage | 250 requests, 1.48M input and 52k output tokens | $1.91 |
| Amazon Bedrock, Claude Sonnet 4.6 | Summaries and promises | 129 requests, 1.05M input and 115k output tokens | $5.37 |
| Apify Website Content Crawler | Rendering JavaScript-only pages | 3 runs, 51 pages | $0.32 |
| Plain HTTP | Everything else | 1,216 pages (102 failed) | free |

Bedrock costs are computed from the returned token counts at list prices plus 10% for EU regional inference profiles. The total for both files, including development reruns that tightened the filters, was about $12.5; a rerun from the cache costs nothing.

## Limits and failure modes

- **Coverage is search-bound.** A programme that Exa does not surface and that is not linked from a surfaced page is reported `not_found`, even if it exists. `not_found` means "not found by this method on 9 October", not "has no programme".
- **Model judgement.** The triage and extraction models decide which pages are the programme and which commitments are concrete. They can pick a partial page (one chapter) or miss one. The verbatim quote check prevents invented quotes; it does not prove that a paraphrase is a perfect translation, so the app shows the Czech quote with every paraphrase.
- **Conservative checks.** A real programme is rejected when its page names neither the city nor a leading candidate (a party page that only says "our town"), or when the triage or extraction model judges it to be news coverage. Rejections carry a `note` and are counted above.
- **Long documents.** At most 90,000 characters go to the extraction model; promises after that point in a very long PDF are not considered. Quotes are still verified against the full text.
- **Text extraction.** PDFs with unusual font encodings or scanned pages yield little or garbled text; those programmes end up with few or no promises. JavaScript-only sites need the Apify render step.
- **Name matching.** Exact full names in any grammatical case catch most coverage, but nicknames, surname-only headlines ("lídr Hrubý") and transliterated names are missed. A namesake in the same city with the same full name would be matched; the city requirement makes this rare, not impossible.
- **News search.** Exa's news index has gaps for small local outlets and paywalled sites, and its publication dates are occasionally missing; undated results are dropped (iDNES and Lidovky dates are read from their article ids).
- **Point in time.** Programmes were fetched on 9 October 2026, the first day of voting. Pages can change or disappear later; the fetch time is stored with every entry.

## Responsibility

Only public pages published by the lists and public news articles are used. Nothing is inferred about candidates' or voters' personal traits, there is no voter profiling and no persuasion. Programme summaries are neutral and descriptive; they do not rate, rank or fact-check promises. Corrections can be requested through [GitHub issues](https://github.com/1vecera/starwatch/issues).
