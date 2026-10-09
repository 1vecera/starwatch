"""Wikidata: Czech politicians with official social-media handles, party membership and IDs (CC0)."""
from __future__ import annotations

import json

import httpx

from ..land import UA, manifest_append, now_iso
from ..paths import RAW

ENDPOINT = "https://query.wikidata.org/sparql"

Q_PEOPLE = """
SELECT DISTINCT ?p ?pLabel ?birth ?fb ?ig ?x ?tt ?yt ?web ?pspid ?party WHERE {
  { ?p wdt:P106 wd:Q82955 . } UNION { ?p wdt:P102 ?pp . ?pp wdt:P17 wd:Q213 . }
  ?p wdt:P27 wd:Q213 .
  OPTIONAL { ?p wdt:P2013 ?fb } OPTIONAL { ?p wdt:P2003 ?ig } OPTIONAL { ?p wdt:P2002 ?x }
  OPTIONAL { ?p wdt:P7085 ?tt } OPTIONAL { ?p wdt:P2397 ?yt }
  FILTER(BOUND(?fb) || BOUND(?ig) || BOUND(?x) || BOUND(?tt) || BOUND(?yt))
  OPTIONAL { ?p wdt:P569 ?birth } OPTIONAL { ?p wdt:P856 ?web } OPTIONAL { ?p wdt:P6828 ?pspid }
  OPTIONAL { ?p wdt:P102 ?party }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "cs,en". }
}
"""

Q_PARTIES = """
SELECT DISTINCT ?party ?partyLabel ?ico ?web ?fb ?ig ?x ?tt ?yt ?inception ?dissolved ?shortname WHERE {
  ?party wdt:P31/wdt:P279* wd:Q7278 ; wdt:P17 wd:Q213 .
  OPTIONAL { ?party wdt:P4156 ?ico } OPTIONAL { ?party wdt:P856 ?web }
  OPTIONAL { ?party wdt:P2013 ?fb } OPTIONAL { ?party wdt:P2003 ?ig } OPTIONAL { ?party wdt:P2002 ?x }
  OPTIONAL { ?party wdt:P7085 ?tt } OPTIONAL { ?party wdt:P2397 ?yt }
  OPTIONAL { ?party wdt:P571 ?inception } OPTIONAL { ?party wdt:P576 ?dissolved }
  OPTIONAL { ?party wdt:P1813 ?shortname }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "cs,en". }
}
"""


def run(name: str, q: str) -> int:
    r = httpx.get(ENDPOINT, params={"query": q, "format": "json"},
                  headers={"User-Agent": UA, "Accept": "application/sparql-results+json"}, timeout=180)
    r.raise_for_status()
    data = r.json()
    p = RAW / "wikidata" / f"{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False))
    manifest_append({"source": "wikidata", "source_url": f"{ENDPOINT}?query=<{name}>", "final_url": ENDPOINT,
                     "fetched_at": now_iso(), "path": str(p), "bytes": p.stat().st_size, "sha256": None,
                     "content_type": "application/sparql-results+json", "apify_run_id": None, "query": q})
    return len(data["results"]["bindings"])


def run_retry(name: str, q: str, tries: int = 8, wait: int = 75) -> int:
    import time
    for i in range(tries):
        try:
            return run(name, q)
        except Exception as ex:  # noqa: BLE001
            print(name, "attempt", i, "failed:", str(ex)[:120], flush=True)
            time.sleep(wait)
    return -1


if __name__ == "__main__":
    import time
    print("people", run_retry("cz_politicians", Q_PEOPLE), flush=True)
    time.sleep(70)
    print("parties", run_retry("cz_parties", Q_PARTIES), flush=True)
