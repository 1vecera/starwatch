"""Czech name matching used to tie news articles to lists and candidates."""

from __future__ import annotations

import pytest

from czlake.campaign.names import (brand_pattern, city_pattern, distinctive_name, parties_in, party_pattern,
                                   person_pattern, word_forms)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Tomáš Hrubý", "říká ústecký lídr Tomáš Hrubý"),
        ("Tomáš Hrubý", "rozhovor s Tomášem Hrubým"),
        ("Zdeněk Žák", "podle Zdeňka Žáka"),
        ("Klára Sovová", "s Klárou Sovovou"),
        ("Pavel Hlaváček", "kandidátka Pavla Hlaváčka"),
        ("Jiří Hájek", "podle Jiřího Hájka"),
        ("Lenka Brčková", "pro Lenku Brčkovou"),
    ],
)
def test_declined_full_names_match(name, text):
    assert person_pattern(name).search(text)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Tomáš Hrubý", "lídr Hrubý řekl"),  # surname alone is not enough
        ("Tomáš Hrubý", "Tomáš Hrubeš"),  # different surname
        ("Jan Teplý", "jan teplý"),  # capitalisation is part of the name
        ("Jan Novák", "Jana Nováková"),  # a different person
    ],
)
def test_partial_or_different_names_do_not_match(name, text):
    assert not person_pattern(name).search(text)


def test_word_forms_cover_fleeting_e():
    assert {"Pavla", "Pavlovi"} <= word_forms("Pavel")
    assert "Němce" in word_forms("Němec")


@pytest.mark.parametrize(
    ("city", "text"),
    [("Brno", "v Brně"), ("Pardubice", "v Pardubicích"), ("Plzeň", "plzeňský primátor"),
     ("Ústí nad Labem", "v Ústí nad Labem"), ("Hradec Králové", "v Hradci Králové")],
)
def test_city_forms(city, text):
    assert city_pattern(city).search(text)


def test_city_forms_need_a_word_boundary():
    assert not city_pattern("Brno").search("Brnoklidem")


def test_party_names_are_case_sensitive():
    assert party_pattern("ANO").search("lídr ANO v Ústí")
    assert not party_pattern("ANO").search("ano, řekl")
    assert party_pattern("STAN").search("Starostové v Plzni")
    assert not party_pattern("STAN").search("starosta obvodu")


def test_list_brands_and_parties():
    assert distinctive_name("PRAHA SOBĚ") == "PRAHA SOBĚ"
    assert distinctive_name("srdcOVA - ODS, Lidovci, TOP 09 a nestraníci") == "srdcOVA"
    assert distinctive_name("ANO 2011") is None
    assert distinctive_name("STAROSTOVÉ A NEZÁVISLÍ") is None
    assert distinctive_name("Svoboda a přímá demokracie (SPD)") is None
    assert parties_in("MILUJEME OLOMOUC - Piráti, TOP 09, Zelení") == ["Piráti", "TOP 09", "Zelení"]


def test_brand_needs_capitalised_start():
    assert brand_pattern("PRAHA SOBĚ").search("hnutí Praha sobě")
    assert brand_pattern("Ostravak").search("kandidát Ostravaku")
    assert not brand_pattern("PRO PLZEŇ").search("peníze pro Plzeň")
    assert brand_pattern("srdcOVA").search("koalice srdcOVA")
