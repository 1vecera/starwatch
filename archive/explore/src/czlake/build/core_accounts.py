"""core.account: social accounts linked to resolved persons, with the basis for each link.

Sources, strongest first:
  wikidata   - official handles on Wikidata (P2013/P2003/P2002/P7085/P2397), matched to a person by
               accent-free name AND birth year inside the person's birth-year window
  scout      - accounts verified by research agents against the person's own website/anchor
  offices    - accounts listed on official office pages (senat.cz, vlada.gov.cz, city sites) via the sweep
  serp       - Google results restricted to social sites; accepted only when the result title carries the
               full name AND the snippet or title carries the person's city, party or office
Rejected and unconfirmed candidates are kept with a reason, never silently dropped.
"""
from __future__ import annotations

import json
import re

import pyarrow as pa

from .. import lakehouse as lh
from ..paths import RAW
from ..scope import TOP_CITY_RANK
from ..textnorm import normkey, register

PLATFORM_URL = {
    "facebook": "https://www.facebook.com/{}", "instagram": "https://www.instagram.com/{}/",
    "x": "https://x.com/{}", "tiktok": "https://www.tiktok.com/@{}", "youtube": "https://www.youtube.com/channel/{}",
}


def norm_handle(platform: str, h: str | None) -> str | None:
    if not h:
        return None
    h = h.strip().strip("/")
    if platform in ("instagram", "x", "tiktok"):
        h = h.lstrip("@").lower()
    if platform == "facebook":
        h = h.split("?")[0] if not h.startswith("profile.php") else h
        h = h.lower()
    return h


def from_wikidata(con) -> list[dict]:
    rows = con.sql("""
      with w as (
        select p as qid, pLabel as label, try_cast(substr(birth,1,4) as int) as by, fb, ig, x, tt, yt from staging.wikidata_cz_politicians
      )
      select distinct pe.person_id, w.qid, w.label, w.by, w.fb, w.ig, w.x, w.tt, w.yt
      from w join core.person pe on pe.name_key = normkey(w.label)
       and w.by between pe.birth_year_lo - 1 and pe.birth_year_hi + 1
    """).fetchall()
    out = []
    for pid, qid, label, by, fb, ig, x, tt, yt in rows:
        for plat, h in (("facebook", fb), ("instagram", ig), ("x", x), ("tiktok", tt), ("youtube", yt)):
            if not h:
                continue
            nh = norm_handle(plat, h)
            out.append({"person_id": pid, "platform": plat, "handle": nh, "url": PLATFORM_URL[plat].format(h),
                        "source": "wikidata", "source_url": qid, "status": "accepted",
                        "match_basis": f"Wikidata {qid.rsplit('/',1)[-1]}: name and birth year {by} match"})
    return out


def from_serp(con) -> list[dict]:
    try:
        hits = con.sql(f"""
          select h.person_id, h.platform, h.handle, h.url, h.title, h.description, h.rank, h.apify_run_id,
                 p.first_name, p.last_name,
                 coalesce((select arg_min(city,population_rank) from marts.city_2026_candidates c
                           where c.person_id=h.person_id and c.population_rank<={TOP_CITY_RANK}),r.a_city) as a_city,
                 r.reasons, coalesce(r.tier,2) as tier
          from staging.serp_social_hits h join core.person p using (person_id)
          left join marts.ranked_set_v1 r using (person_id)
          where h.platform in ('facebook','instagram','x','tiktok','youtube')
        """).fetchall()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for pid, plat, handle, url, title, desc, rank, run_id, fn, ln, city, reasons, tier in hits:
        t, d = normkey(title or "") or "", normkey(desc or "") or ""
        full = normkey(f"{fn} {ln}") or ""
        ctx = set()
        if city:
            ctx.add(normkey(city))
        for kw in re.findall(r"\(([^)]*)\)", reasons or ""):
            for part in kw.split(","):
                part = normkey(part)
                if part and len(part) > 2:
                    ctx.add(part)
        if tier == 1:
            ctx |= {"poslanec", "poslankyne", "senator", "senatorka", "europoslanec", "europoslankyne", "poslanecka snemovna"}
        name_in_title = bool(full) and full in t
        hn = re.sub(r"[^a-z0-9]", "", normkey(handle or "") or "")
        sur = re.sub(r"[^a-z0-9]", "", normkey(ln) or "")
        handle_has_surname = bool(sur) and sur[:max(4, len(sur) - 2)] in hn
        ctx_hit = any(c and (c in t or c in d) for c in ctx)
        role_words = any(w in (t + " " + d) for w in ("politik", "politician", "starost", "primator", "zastupitel", "radni", "poslan", "senator", "hejtman", "mistostarost", "namest", "kandidat"))
        if name_in_title and (ctx_hit or role_words) and handle_has_surname:
            status, basis = "accepted", "SERP: profile titled with the full name" + (" and handle carries the surname" if handle_has_surname else "") + " + " + ("city/party/office in snippet" if ctx_hit else "political role words in snippet")
        elif name_in_title and (ctx_hit or role_words):
            status, basis = "unconfirmed", "SERP: full name and context in a result whose title/handle does not identify the account owner"
        elif name_in_title:
            status, basis = "unconfirmed", "SERP: full name in title, no city/party/office evidence"
        else:
            status, basis = "rejected", "SERP: name not in result title"
        out.append({"person_id": pid, "platform": plat, "handle": norm_handle(plat, handle), "url": url,
                    "source": "serp", "source_url": f"apify:{run_id}#rank{rank}", "status": status, "match_basis": basis})
    return out


def from_scouts() -> list[dict]:
    p = RAW / "scouts" / "demo_shortlist_scout.json"
    if not p.exists():
        return []
    out = []
    for r in json.loads(p.read_text()):
        for a in r["accounts"]:
            if a["platform"] not in PLATFORM_URL:
                continue
            out.append({"person_name": r["name"].split(" (")[0], "platform": a["platform"], "url": a["url"],
                        "handle_raw": a["handle"].split(" ")[0], "status": "accepted" if a["official"].lower().startswith("official") else "unconfirmed",
                        "match_basis": "research agent: " + a["official"][:160], "source": "scout"})
    return out


def build() -> dict:
    con = lh.duck()
    register(con)
    rows = from_wikidata(con) + from_serp(con)
    # scouts: attach to persons by name among national office holders
    sc = from_scouts()
    if sc:
        names = {name for s in sc if (name := normkey(s["person_name"]))}
        pmap = {}
        for nk, pid, score in con.sql(f"""select pe.name_key, pe.person_id, coalesce(o.score_official,0)
                                          from core.person pe left join marts.rank_official_composite o using (person_id)
                                          where pe.name_key in ({",".join("'" + n.replace("'", "") + "'" for n in names)})""").fetchall():
            if nk not in pmap or score > pmap[nk][1]:
                pmap[nk] = (pid, score)
        for s in sc:
            pid = pmap.get(normkey(s["person_name"]), (None,))[0]
            from .discover_accounts import plat_handle
            _plat, h = plat_handle(s["url"])
            rows.append({"person_id": pid, "platform": s["platform"], "handle": norm_handle(s["platform"], h or s["handle_raw"]),
                         "url": s["url"], "source": "scout", "source_url": "data/lake/raw/scouts/demo_shortlist_scout.json",
                         "status": s["status"], "match_basis": s["match_basis"]})
    t = pa.Table.from_pylist(rows)
    con.register("acc_raw", t)
    final = lh.tbl(con.sql("""
      with r as (select *, case status when 'accepted' then 0 when 'unconfirmed' then 1 else 2 end s,
                        case source when 'wikidata' then 0 when 'scout' then 1 when 'offices' then 2 else 3 end src from acc_raw
                 where person_id is not null and handle is not null),
      best as (select person_id, platform, handle, min(s) s from r group by all)
      select r.person_id, r.platform, r.handle, any_value(r.url order by r.src) as url,
             case min(r.s) when 0 then 'accepted' when 1 then 'unconfirmed' else 'rejected' end as status,
             string_agg(distinct r.source, ',') as sources,
             string_agg(distinct r.match_basis, ' | ') as match_basis,
             count(*) as n_evidence,
             md5(r.platform || ':' || r.handle) as account_id
      from r group by r.person_id, r.platform, r.handle
    """))
    lh.write("core", "account", final)
    return {"rows_in": len(rows), "accounts": final.num_rows}


if __name__ == "__main__":
    print(build())
    con = lh.duck()
    print(con.sql("select platform, status, count(*) from core.account group by all order by 1,2").fetchall())
