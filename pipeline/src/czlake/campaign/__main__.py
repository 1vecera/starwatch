"""Command line for the programme and article collectors.

Examples (from ``pipeline/``)::

    uv run python -m czlake.campaign --snapshot ../app/web/data/real.js --cache ../tmp/campaign \\
        programs --lists relevant --out ../app/web/data/programs.js
    uv run python -m czlake.campaign --snapshot ../app/web/data/real.js --cache ../tmp/campaign \\
        articles --lists all --out ../app/web/data/articles.js
    uv run python -m czlake.campaign --cache ../tmp/campaign spend

Add ``--offline`` to rebuild the outputs from the cache only (no network, no spend).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .common import Cache, Ledger, read_js, write_js
from .text import registered_domain

DEFAULT_CAPS = {"exa": 10.0, "bedrock": 20.0, "apify": 15.0}


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m czlake.campaign",
        description="Collect official election programmes (with verbatim-checked promises) and Czech news "
                    "articles for the lists in a Starwatch snapshot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Credentials are read from the environment only: EXA_API_KEY, APIFY_TOKEN and AWS credentials "
               "(standard chain, or <prefix>AWS_ACCESS_KEY_ID/<prefix>AWS_SECRET_ACCESS_KEY with "
               "--aws-env-prefix). Spend caps are cumulative across runs that share --cache.",
    )
    parser.add_argument("--snapshot", type=Path, help="real.js snapshot (window.SW_RAW)")
    parser.add_argument("--cache", type=Path, required=True,
                        help="directory for raw responses, fetched pages and the spend ledger (keep out of Git)")
    parser.add_argument("--offline", action="store_true", help="use cached responses only; never call a service")
    for service, label in (("exa", "Exa"), ("bedrock", "Bedrock"), ("apify", "Apify")):
        parser.add_argument(f"--max-{service}-usd", type=float, default=DEFAULT_CAPS[service],
                            help=f"hard cap on cumulative {label} spend in USD (default {DEFAULT_CAPS[service]:g})")
    parser.add_argument("--aws-env-prefix", default="",
                        help="read AWS keys from <prefix>AWS_ACCESS_KEY_ID etc. instead of the default chain")
    commands = parser.add_subparsers(dest="command", required=True)

    programs = commands.add_parser("programs", help="find programmes and extract verified promises")
    programs.add_argument("--lists", choices=["relevant", "rest", "all"], default="relevant",
                          help="which snapshot lists to process (default: relevant)")
    programs.add_argument("--ids", nargs="*", help="explicit list ids instead of --lists")
    programs.add_argument("--out", type=Path, required=True, help="programs.js to write (window.SW_PROGRAMS)")
    programs.add_argument("--merge", action="store_true",
                          help="keep entries already in --out for lists outside this selection")
    programs.add_argument("--no-render", action="store_true", help="never call Apify for JavaScript-only pages")
    programs.add_argument("--triage-model", default=None, help="Bedrock model id for candidate triage")
    programs.add_argument("--extract-model", default=None, help="Bedrock model id for summaries and promises")
    programs.add_argument("--workers", type=int, default=4,
                          help="parallel lists per phase; lower it if Bedrock throttles (default 4)")

    articles = commands.add_parser("articles", help="find news articles naming lists or leading candidates")
    articles.add_argument("--lists", choices=["relevant", "rest", "all"], default="relevant",
                          help="which snapshot lists to search for (default: relevant)")
    articles.add_argument("--ids", nargs="*", help="explicit list ids instead of --lists")
    articles.add_argument("--out", type=Path, required=True, help="articles.js to write (window.SW_ARTICLES)")
    articles.add_argument("--programs", type=Path,
                          help="programs.js; its programme domains are excluded from news results")

    commands.add_parser("spend", help="print the cumulative spend recorded in the cache ledger")
    return parser


def _generated_at(values: list[str | None]) -> str:
    """Latest provenance timestamp: equal caches give equal files."""
    present = [value for value in values if value]
    return max(present) if present else "1970-01-01T00:00:00+00:00"


def run_programs(args, snapshot, cache, ledger) -> int:
    from .exa import Exa
    from .llm import DEFAULT_EXTRACT_MODEL, DEFAULT_TRIAGE_MODEL, LLM
    from .programs import ProgramCollector
    from .web import Fetcher, Renderer

    lists = snapshot.select(args.lists, args.ids)
    triage = LLM(cache, ledger, args.triage_model or DEFAULT_TRIAGE_MODEL, env_prefix=args.aws_env_prefix)
    extractor = LLM(cache, ledger, args.extract_model or DEFAULT_EXTRACT_MODEL, env_prefix=args.aws_env_prefix)
    collector = ProgramCollector(
        snapshot, Exa(cache, ledger), Fetcher(cache), None if args.no_render else Renderer(cache, ledger),
        triage, extractor, workers=args.workers, log=_log,
    )
    runs = collector.run(lists)
    entries = {}
    if args.merge and args.out.exists():
        entries = dict(read_js(args.out).get("lists", {}))
    stats = {}
    for run in runs:
        if run.error or not run.entry:
            stats[run.lst.id] = {"status": "error", "error": run.error}
            continue
        entries[run.lst.id] = run.entry
        stats[run.lst.id] = {"status": run.entry["status"], "candidates": len(run.candidates),
                             "selected": [c.url for c in run.selected], "triage": run.triage_reason, **run.stats}
    payload = {
        "generated_at": _generated_at([e.get("fetched_at") or e.get("checked_at") for e in entries.values()]),
        "method": (
            "Each list's own 2026 programme was found with Exa search and programme links on the list's or "
            "party's website, fetched over HTTP (Apify for JavaScript-only pages), summarised by Claude on "
            "Amazon Bedrock, and a promise was kept only if its Czech quote appears verbatim in the fetched text."
        ),
        "lists": dict(sorted(entries.items())),
    }
    write_js(args.out, "SW_PROGRAMS", payload)
    (cache.root / "runs").mkdir(parents=True, exist_ok=True)
    (cache.root / "runs" / "programs-stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1,
                                                                        sort_keys=True))
    _summary_programs(entries, stats, ledger)
    return 0


def _summary_programs(entries: dict, stats: dict, ledger: Ledger) -> None:
    counts: dict[str, int] = {}
    for entry in entries.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    totals = {key: sum(s.get(key, 0) for s in stats.values())
              for key in ("proposed", "kept", "dropped_not_found", "dropped_too_long", "dropped_duplicate",
                          "dropped_over_limit")}
    _log(f"programs: {json.dumps(counts, sort_keys=True)} promises: {json.dumps(totals)}")
    _log(f"spend so far: {json.dumps(ledger.totals())}")


def run_articles(args, snapshot, cache, ledger) -> int:
    from .articles import ArticleCollector
    from .exa import Exa

    lists = snapshot.select(args.lists, args.ids)
    excluded = set()
    if args.programs and args.programs.exists():
        for entry in read_js(args.programs).get("lists", {}).values():
            for source in entry.get("sources", []) or ([{"url": entry["program_url"]}]
                                                        if entry.get("program_url") else []):
                excluded.add(registered_domain(source["url"]))
    collector = ArticleCollector(snapshot, Exa(cache, ledger), extra_excluded=excluded, log=_log)
    items, stats = collector.run(lists)
    payload = {
        "generated_at": _generated_at([item["observed_at"] for item in items]),
        "method": (
            "Exa news search (1 September to 9 October 2026) per city, list and lead candidate; an article is "
            "kept when its title or search highlight names a list or one of its top five candidates together "
            "with the city; poll and betting coverage is excluded and article text is not stored."
        ),
        "items": items,
    }
    write_js(args.out, "SW_ARTICLES", payload)
    (cache.root / "runs").mkdir(parents=True, exist_ok=True)
    (cache.root / "runs" / "articles-stats.json").write_text(json.dumps(stats, indent=1, sort_keys=True))
    _log(f"articles: {json.dumps(stats)}")
    _log(f"spend so far: {json.dumps(ledger.totals())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cache = Cache(args.cache, offline=args.offline)
    ledger = Ledger(args.cache / "spend.jsonl",
                    {"exa": args.max_exa_usd, "bedrock": args.max_bedrock_usd, "apify": args.max_apify_usd})
    if args.command == "spend":
        print(json.dumps({"spent_usd": ledger.totals(), "caps_usd": ledger.caps}, indent=1))
        return 0
    snapshot_path = args.snapshot or Path(os.environ.get("STARWATCH_SNAPSHOT", "../app/web/data/real.js"))
    from .snapshot import load

    snapshot = load(snapshot_path)
    if args.command == "programs":
        return run_programs(args, snapshot, cache, ledger)
    return run_articles(args, snapshot, cache, ledger)


if __name__ == "__main__":
    sys.exit(main())
