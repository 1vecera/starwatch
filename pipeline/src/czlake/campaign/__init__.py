"""Election programmes and news coverage for the Starwatch snapshot.

Two commands share one cache and one spend ledger:

- ``programs`` finds each list's own 2026 municipal programme, extracts its text and keeps
  promises whose Czech quote is found verbatim in that text.
- ``articles`` finds Czech news articles that name a list or one of its leading candidates
  together with the city, and keeps only title, outlet, date, URL and match evidence.

Run ``uv run python -m czlake.campaign --help`` for usage; see
``docs/collection/programs-and-articles.md`` for the full recipe.
"""
