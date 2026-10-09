"""Download every CSV open-data zip (registries, code lists, results) for selected volby.cz elections."""
from __future__ import annotations

import re
import sys

import httpx

from ..land import UA, land_url

BASE = "https://volby.gov.cz/opendata"
PAGES = {
    "ps2025": "ps2025/ps2025_opendata.htm", "ps2021": "ps2021/ps2021_opendata.htm",
    "kz2024": "kz2024/kz2024_opendata.htm", "kz2020": "kz2020/kz2020_opendata.htm",
    "kv2026": "kv2026/kv2026_opendata.htm", "kv2022": "kv2022/kv2022_opendata.htm",
    "kv2018": "kv2018/kv2018_opendata.htm",
    "se2026": "se2026/se2026_opendata.htm", "se2025leden": "se2025leden/se2025leden_opendata.htm",
    "se2024": "se2024/se2024_opendata.htm", "se2022": "se2022/se2022_opendata.htm",
    "se2020": "se2020/se2020_opendata.htm", "senat_vse": "senat_vse/senat_vse_opendata.htm",
    "ep2024": "ep2024/ep2024_opendata.htm", "ep2019": "ep2019/ep2019_opendata.htm",
    "prez2023": "prez2023/prez2023odata.htm",
}


def links(election: str) -> list[str]:
    page = PAGES[election]
    url = f"{BASE}/{page}"
    h = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=60).content.decode("cp1250", "replace")
    base = url.rsplit("/", 1)[0]
    out = []
    for l in re.findall(r'href="([^"]+)"', h):
        low = l.lower()
        if low.endswith(".zip") and ("csv" in low) and "xsd" not in low:
            out.append(l if l.startswith("http") else f"{base}/{l.lstrip('./')}")
    # some elections publish only xlsx/xml; take xml zips when no csv exists
    if not out:
        for l in re.findall(r'href="([^"]+)"', h):
            low = l.lower()
            if low.endswith(".zip") and "xsd" not in low and ("xml" in low or "reg" in low or "cisel" in low):
                out.append(l if l.startswith("http") else f"{base}/{l.lstrip('./')}")
    return sorted(set(out))


if __name__ == "__main__":
    for e in (sys.argv[1:] or PAGES):
        try:
            ls = links(e)
        except Exception as ex:  # noqa: BLE001
            print(e, "INDEX-FAIL", ex)
            continue
        for u in ls:
            try:
                p = land_url(u, f"volby_{e}", extract=True)
                print(e, "ok", p.name)
            except Exception as ex:  # noqa: BLE001
                print(e, "FAIL", u, ex)
