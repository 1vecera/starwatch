# Contributing to Starwatch

Thanks for helping. Starwatch is a small, non-commercial project about public political communication, so the most valuable contributions are corrections, better sources and careful fixes. Please read the [political-research rules](#political-research-rules) before proposing anything that touches data.

## Run it locally

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```sh
./run.sh                 # the app with the labelled simulated universe, at http://127.0.0.1:5173/
PORT=8080 ./run.sh       # another port
```

The app in `app/web` is static HTML, CSS and JavaScript with no build step; edit a file and reload. Python runs through `uv`; each Python component has its own `pyproject.toml` and lockfile.

Run the checks before opening a pull request:

```sh
(cd pipeline && uv sync && uv run --with pytest pytest)
(cd app && uv run --with pytest pytest tools/test_serve.py)
(cd deploy/edge && npm ci && npm test)    # sign-in Worker and CloudFront gate; needs Node.js
```

Tests must not call Apify, other paid services or live websites; use local fixtures. Collection needs your own `APIFY_TOKEN` in the environment and is described in [docs/apify-recipes.md](docs/apify-recipes.md) and [pipeline/README.md](pipeline/README.md). Never commit credentials, `.env` files, collected posts, media, exported snapshots or DuckDB checkpoints; `.gitignore` keeps the usual locations out, but check `git status` before you commit.

## Corrections and removal requests

Open an [issue](https://github.com/1vecera/starwatch/issues) with:

- the screen and the person, list or post concerned;
- what is wrong (for example, an account attributed to the wrong candidate, a namesake, a wrong list or a broken source link);
- a public source that shows the correct fact, with the date you checked it.

Candidates who want a post or account removed from the app can ask in an issue. If you prefer not to write publicly, message Daniel Večeřa on [LinkedIn](https://www.linkedin.com/in/1vecera/) or [X](https://x.com/1vecera). Remember that the app shows a dated snapshot (8–9 October 2026); a correction fixes the attribution or removes the item, it does not refresh the collection.

## Proposing sources

New sources are welcome when they are public and add evidence about candidates or lists in the covered cities: an official candidate or list account that was missed, a published program, or an official results or registry dataset. In the issue, give the URL, who publishes it, why it is official (for example, linked from the list's website or the candidate's own profile) and the date you checked it. An account is attributed to a person only with an independent public anchor; a matching name alone is not enough.

## Code contributions

- Keep pull requests small and focused, and say what you changed and how you checked it.
- Add or update a test when you change behaviour.
- Keep unknown values unknown; do not fill gaps with guesses or merge separate measures into one score.
- Match the style of the file you change: plain JavaScript and CSS in `app/web`, Python run through `uv` in `pipeline/`.
- `archive/` is historical; changes there are accepted only to keep it readable.

## Political-research rules

These rules apply to code, data, issues and pull requests alike.

- **Public politicians and public sources only.** No private accounts, closed groups, private messages, leaked material, fake accounts or CAPTCHA bypassing.
- **No data about ordinary people.** Do not collect comments, commenters, followers, likers or anyone who is not a candidate or list.
- **No sensitive inferences.** Do not infer health, religion, ethnicity, sexual orientation or other special-category traits, and do not use face recognition.
- **No scoring of people.** Do not rate anyone's character, honesty or trustworthiness. Confidence belongs to claims and attributions, not to people.
- **No voter profiling or targeted persuasion.** Starwatch describes what candidates publish; it does not build audiences or messaging for campaigns.
- **Metrics are dated observations.** Views, likes and comments measure attention at the time they were observed, not support. Keep the observation time and source with every number.
- **Respect election law.** Do not add opinion polls, forecasts or betting odds in the days before and during voting, when Czech law bans publishing poll results.
- **Link to originals.** Show posts with a link to the source; the collected snapshot stays out of Git and behind sign-in.

## Conduct

Be respectful and assume good faith. Political topics attract strong views; keep discussion about evidence and code, not about parties or people. Personal attacks, harassment and campaigning in issues are removed.
