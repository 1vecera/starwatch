"""Identity resolution: anchor links, name matching and the verdict on every same-name account.

All inputs are invented for the test; no collected data is stored in the repository.
"""

from starwatch.collectors.identity import (
    Candidate,
    SocialLink,
    assess,
    name_match,
    parse_anchor,
    parse_social_url,
    social_links,
)


def test_anchor_parsing():
    assert parse_anchor("example.cz").url == "https://example.cz"
    assert parse_anchor("https://www.example.cz/o-mne").domain == "example.cz"
    party = parse_anchor("Strana zelených, Brno")
    assert party.url == "" and party.terms == ["Strana zelených", "Brno"]


def test_social_links_pick_profiles_not_share_or_post_links():
    hrefs = [
        "https://www.facebook.com/sharer/sharer.php?u=https://example.cz",
        "https://www.facebook.com/janovak.cz/posts/123",
        "https://www.facebook.com/janovak.cz",
        "https://www.instagram.com/p/AbC123/",
        "https://www.instagram.com/jan.novak/",
        "https://twitter.com/intent/tweet?text=x",
        "https://x.com/JanNovak",
        "https://www.youtube.com/watch?v=abc",
        "https://www.youtube.com/@jannovak",
        "https://www.tiktok.com/@jan_novak",
        "https://www.tiktok.com/tag/volby",
    ]
    links = social_links(hrefs)
    assert {p: link.handle for p, link in links.items()} == {
        "facebook": "janovak.cz", "instagram": "jan.novak", "x": "JanNovak",
        "youtube": "@jannovak", "tiktok": "jan_novak",
    }
    assert parse_social_url("https://www.facebook.com/profile.php?id=1000") [0].url.endswith("id=1000")
    assert parse_social_url("https://www.instagram.com/explore/tags/x/") is None


def test_name_match_ignores_titles_and_diacritics_but_not_other_names():
    assert name_match("Jan Novák", "Ing. Jan Novák", "x") == "exact"
    assert name_match("Jan Novák", "JAN NOVAK | makléř", "x") == "contains"
    assert name_match("Jan Novák", "", "jan.novak77") == "handle"
    assert name_match("Jan Novák", "", "novakjan.official") == "handle"
    assert name_match("Jan Novák", "Jana Nováková", "jana.novakova") is None
    assert name_match("Jan Novák", "", "jannovakovic") is None


ANCHOR = parse_anchor("novak.example")
OFFICIAL = SocialLink("instagram", "jan.novak", "https://www.instagram.com/jan.novak/")


def candidate(handle, **fields):
    return Candidate("instagram", handle, f"https://www.instagram.com/{handle}/", **fields)


def test_the_linked_account_is_confirmed_and_namesakes_are_rejected_with_a_reason():
    own = assess(candidate("jan.novak", name="Jan Novák", verified=True, link="https://novak.example/"),
                 "Jan Novák", ANCHOR, OFFICIAL)
    assert own.status == "official" and own.basis == ["verified badge", "bio links novak.example"]

    namesake = assess(candidate("jan.novak.reality", name="Jan Novák", link="https://reality.example",
                                category="Real Estate Agent"), "Jan Novák", ANCHOR, OFFICIAL)
    assert namesake.status == "rejected"
    assert namesake.reason == ("novak.example links @jan.novak, not this account · bio links reality.example"
                               " · profile category Real Estate Agent")
    assert assess(candidate("someone", name="Petra Malá"), "Jan Novák", ANCHOR, OFFICIAL) is None


def test_without_a_linked_account_nothing_is_guessed():
    links_anchor = assess(candidate("jn.official", name="Jan Novák", bio="www.novak.example"), "Jan Novák", ANCHOR, None)
    assert links_anchor.status == "accepted" and "bio links novak.example" in links_anchor.basis

    fan = assess(candidate("jan.novak.fans", name="Jan Novák", bio="neoficiální fanpage"), "Jan Novák", ANCHOR, None)
    assert fan.status == "rejected" and "neoficiáln" in fan.reason

    elsewhere = assess(candidate("jan.novak.foto", name="Jan Novák", link="https://foto.example"), "Jan Novák", ANCHOR, None)
    assert elsewhere.status == "rejected" and "bio links foto.example" in elsewhere.reason

    unknown = assess(candidate("jan.novak.1", name="Jan Novák"), "Jan Novák", ANCHOR, None)
    assert unknown.status == "unconfirmed" and unknown.basis[-1] == "nothing links it to novak.example"


def test_a_party_anchor_needs_the_party_in_the_bio_and_a_badge():
    party = parse_anchor("Strana Příkladů")
    verified = assess(candidate("jn", name="Jan Novák", bio="Poslanec, Strana příkladů", verified=True), "Jan Novák", party, None)
    assert verified.status == "accepted"
    plain = assess(candidate("jn2", name="Jan Novák", bio="Strana příkladů"), "Jan Novák", party, None)
    assert plain.status == "unconfirmed"
