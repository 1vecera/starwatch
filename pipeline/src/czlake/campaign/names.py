"""Exact-name matching for Czech text, tolerant of grammatical case endings.

Czech declines personal names ("Tomáš Hrubý" -> "Tomáše Hrubého"), city names ("Brno" ->
"v Brně") and party names ("Piráti" -> "Pirátů"). Matching stays exact in every other way: a
candidate matches only as first name followed by surname, both capitalised as written, and the
caller additionally requires city or list context to guard against namesakes.
"""

from __future__ import annotations

import re
from functools import lru_cache

_SOFT = {"k": "c", "h": "z", "g": "z", "r": "ř", "ch": "š", "d": "ď", "t": "ť", "n": "ň"}
_VOWELS = "aáeéěiíoóuúůyý"


def word_forms(word: str) -> set[str]:
    """Plausible case forms of one capitalised Czech name token (nominative given)."""
    forms = {word}
    low = word.lower()
    if len(word) < 2:
        return forms
    if low.endswith(("ová", "ská", "cká", "ná", "á")) and not low.endswith("iá"):
        stem = word[:-1]
        forms |= {stem + "é", stem + "ou"}
    elif low.endswith("ý"):
        stem = word[:-1]
        forms |= {stem + ending for ending in ("ého", "ému", "ým", "ém")}
    elif low.endswith("í"):
        forms |= {word + ending for ending in ("ho", "mu", "m")}
    elif low.endswith("a"):
        stem = word[:-1]
        forms |= {stem + ending for ending in ("y", "u", "ou", "o", "ovi", "e", "ě", "i")}
        for hard, soft in _SOFT.items():
            if stem.endswith(hard):
                forms.add(stem[: -len(hard)] + soft + "e")
    elif low.endswith("e") or low.endswith("ě"):
        stem = word[:-1]
        forms |= {word + ending for ending in ("ho", "mu")} | {stem + ending for ending in ("i", "em", "ovi")}
    elif low.endswith("o"):
        stem = word[:-1]
        forms |= {stem + ending for ending in ("a", "ovi", "em", "u")}
    elif low[-1] not in _VOWELS:
        forms |= {word + ending for ending in ("a", "e", "ě", "i", "ovi", "em", "u", "ům", "ových")}
        if len(low) > 3 and low[-2] == "e" and low[-1] in "klcrn" and low[-3] not in _VOWELS:
            stem = word[:-2] + word[-1]  # fleeting e: Pavel -> Pavla, Hlaváček -> Hlaváčka, Němec -> Němce
            forms |= {stem + ending for ending in ("a", "e", "i", "ovi", "em", "u")}
        if low.endswith("ěk") and len(low) > 3:
            soft = {"d": "ď", "t": "ť", "n": "ň"}.get(word[-3], word[-3])
            stem = word[:-3] + soft + "k"  # Zdeněk -> Zdeňka
            forms |= {stem + ending for ending in ("a", "ovi", "em", "u")}
    return forms


def _alternation(forms: set[str]) -> str:
    return "(?:" + "|".join(re.escape(form) for form in sorted(forms, key=lambda f: (-len(f), f))) + ")"


@lru_cache(maxsize=None)
def person_pattern(full_name: str) -> re.Pattern | None:
    """First name(s) then surname, each in any case form; tokens separated by whitespace."""
    tokens = [token for token in re.split(r"\s+", full_name.strip()) if token]
    titles = r"(?:Ing|Mgr|Bc|MUDr|JUDr|PhDr|RNDr|Dr|doc|prof)\.?"
    tokens = [token for token in tokens if not re.fullmatch(titles, token)]
    if len(tokens) < 2:
        return None
    pieces = [_alternation(word_forms(token)) for token in tokens]
    return re.compile(r"(?<![\w-])" + r"\s+".join(pieces) + r"(?![\w-])")


# Cities: case forms plus resident adjectives/demonyms. A trailing "*" marks a prefix (stem).
CITY_FORMS: dict[str, tuple[str, ...]] = {
    "Praha": ("Praha", "Prahy", "Praze", "Prahu", "Prahou", "pražsk*", "Pražsk*", "Pražan*"),
    "Brno": ("Brno", "Brna", "Brně", "Brnu", "Brnem", "brněnsk*", "Brněnsk*", "Brňan*"),
    "Ostrava": ("Ostrava", "Ostravy", "Ostravě", "Ostravu", "Ostravou", "ostravsk*", "Ostravsk*", "Ostravan*",
                "Ostravák*"),
    "Plzeň": ("Plzeň", "Plzně", "Plzni", "Plzní", "plzeňsk*", "Plzeňsk*", "Plzeňan*", "Plzeňák*"),
    "Liberec": ("Liberec", "Liberce", "Liberci", "Libercem", "libereck*", "Libereck*", "Liberečan*"),
    "Olomouc": ("Olomouc", "Olomouce", "Olomouci", "olomouck*", "Olomouck*", "Olomoučan*"),
    "České Budějovice": ("Budějovic*", "budějovick*", "Budějovick*", "Budějčák*", "Budějovičan*"),
    "Ústí nad Labem": ("Ústí nad Labem", "Ústí", "ústeck*", "Ústeck*", "Ústečan*", "Ústečák*"),
    "Hradec Králové": ("Hradec Králové", "Hradce Králové", "Hradci Králové", "Hradec", "Hradci", "Hradce",
                       "hradeck*", "Hradeck*", "Hradečák*", "Hradečan*"),
    "Pardubice": ("Pardubic*", "pardubick*", "Pardubick*", "Pardubičan*", "Pardubák*"),
}


@lru_cache(maxsize=None)
def city_pattern(city: str) -> re.Pattern:
    forms = CITY_FORMS.get(city) or tuple(sorted(word_forms(city)))
    pieces = [re.escape(form[:-1]) + r"\w*" if form.endswith("*") else re.escape(form) for form in forms]
    return re.compile(r"(?<!\w)(?:" + "|".join(sorted(pieces, key=len, reverse=True)) + r")(?!\w)")


# Party and movement names as they appear in news text. Case-sensitive on purpose: "ANO" the
# movement is not "ano" (yes), "Starostové" the movement is not "starosta" (mayor).
PARTY_PATTERNS: dict[str, str] = {
    "ANO": r"(?<![\w-])ANO(?![\w-])",
    "ODS": r"(?<![\w-])ODS(?![\w-])|[Oo]bčansk\w+ demokrat\w+",
    "SPD": r"(?<![\w-])SPD(?![\w-])",
    "Piráti": r"(?<![\w-])Pirát\w*|(?<![\w-])pirát(?:i|ů|ům|y|ech)(?![\w-])",
    "STAN": r"(?<![\w-])STAN(?![\w-])|(?<![\w-])Starostov\w*|(?<![\w-])Starostů(?![\w-])|STAROSTOVÉ",
    "KDU-ČSL": r"KDU-ČSL|(?<![\w-])[Ll]idovc\w*",
    "TOP 09": r"TOP 09|TOP09",
    "Motoristé": r"(?<![\w-])Motorist\w*",
    "Zelení": r"(?<![\w-])Zelen(?:í|ých|ým|ými)(?![\w-])",
    "Trikolora": r"(?<![\w-])Trikolor\w*",
    "Svobodní": r"(?<![\w-])Svobodn(?:í|ých|ým|ými)(?![\w-])",
    "Přísaha": r"(?<![\w-])P[řŘ]ÍSAH\w*|(?<![\w-])Přísah\w*",
    "Stačilo!": r"(?<![\w-])Stačilo!|STAČILO!",
    "KSČM": r"KSČM|[Kk]omunist\w+",
    "SOCDEM": r"SOCDEM|ČSSD|[Ss]ociální demokrac\w+",
    "SPOLU": r"(?<![\w-])SPOLU(?![\w-])|[Kk]oalic\w+ Spolu(?![\w-])",
}
_PARTY_IN_LIST_NAME: dict[str, str] = {
    "ANO": r"ANO 2011|ANO a",
    "ODS": r"ODS|Občanská demokratická strana",
    "SPD": r"SPD|Svoboda a přímá demokracie",
    "Piráti": r"Piráti|[Pp]irátsk|PIRÁTI",
    "STAN": r"STAROSTOVÉ|Starostové|STAN",
    "KDU-ČSL": r"KDU-ČSL|[Ll]idovc|lidovců",
    "TOP 09": r"TOP 09",
    "Motoristé": r"Motoristé",
    "Zelení": r"Zelen",
    "Trikolora": r"Trikolor|TRIKOLOR",
    "Svobodní": r"Svobodn|SVOBODN",
    "Přísaha": r"PŘÍSAH|Přísah",
    "Stačilo!": r"Stačilo",
    "KSČM": r"KSČM|Komunistická",
    "SOCDEM": r"SOCDEM|Sociální demokracie|ČSSD",
    "SPOLU": r"SPOLU",
}


def parties_in(list_name: str) -> list[str]:
    """Parties named in an official list name, e.g. coalition members."""
    return [party for party, pattern in _PARTY_IN_LIST_NAME.items() if re.search(pattern, list_name)]


@lru_cache(maxsize=None)
def party_pattern(party: str) -> re.Pattern:
    return re.compile(PARTY_PATTERNS[party])


_SPLIT = re.compile(r"\s+(?:-|–|—|s podporou|a nezávislí)\s+|\s*\(|:\s|;\s|,\s")
_FILLER = {"a", "s", "se", "pro", "sobě", "2011", "09", "nezávislí", "nezávislých", "strana", "hnutí", "koalice",
           "česká", "+", "&", "demokratická"}


def distinctive_name(list_name: str) -> str | None:
    """A list's own brand (e.g. "PRAHA SOBĚ", "Ostravak"), or None for plain party names."""
    head = _SPLIT.split(list_name.strip(), maxsplit=1)[0].strip(" ,.")
    rest = head
    for pattern in _PARTY_IN_LIST_NAME.values():
        rest = re.sub(r"\S*(?:" + pattern + r")\S*", " ", rest)
    remaining = [word for word in rest.split() if word.lower() not in _FILLER]
    if len(head) < 5 or not remaining or sum(len(word) for word in remaining) < 4:
        return None
    return head


@lru_cache(maxsize=None)
def brand_pattern(name: str) -> re.Pattern:
    """Brand words in order, case-insensitive except the first letter, last word may decline."""
    words = name.split()
    pieces = []
    for index, word in enumerate(words):
        suffix = r"\w{0,3}" if index == len(words) - 1 and word[-1].isalpha() else ""
        if index == 0:
            first = re.escape(word[0]) if word[0].isupper() or not word[0].isalpha() else \
                f"[{re.escape(word[0])}{re.escape(word[0].upper())}]"
            pieces.append(first + "(?i:" + re.escape(word[1:]) + suffix + ")")
        else:
            pieces.append("(?i:" + re.escape(word) + suffix + ")")
    return re.compile(r"(?<![\w-])" + r"\s+".join(pieces) + r"(?![\w-])")
