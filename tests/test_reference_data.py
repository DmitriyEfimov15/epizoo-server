"""Проверки целостности справочников, используемых нормализацией и картой."""

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml
from shapely.geometry import shape

DATA = Path(__file__).resolve().parents[1] / "data"
SPECIES = {
    "cattle",
    "small_ruminants",
    "pigs",
    "poultry",
    "horses",
    "bees",
    "rabbits",
    "carnivores",
    "wildlife",
}


def read_yaml(name):
    path = DATA / name
    assert path.exists(), f"Отсутствует справочник {name}"
    rows = yaml.safe_load(path.read_text())
    assert isinstance(rows, list) and rows
    return rows


def test_regions_have_unique_codes_and_unambiguous_aliases():
    regions = read_yaml("regions.yaml")
    assert len(regions) == 89
    codes = {row["code"] for row in regions}
    assert len(codes) == 89
    aliases = {}
    for row in regions:
        assert re.fullmatch(r"\d{2}", row["code"])
        assert row["name"] and row["federal_district"]
        for alias in [row["name"], *row["aliases"]]:
            normalized = alias.casefold().replace("ё", "е")
            assert aliases.get(normalized, row["code"]) == row["code"]
            aliases[normalized] = row["code"]
        assert row["code"] not in row["neighbors"]
        assert set(row["neighbors"]) <= codes
    assert aliases["донецкая народная республика"] == "93"
    assert aliases["кемеровская область"] == "42"
    assert aliases["алтайской край"] == "22"
    assert aliases["республика удмуртия"] == "18"
    assert aliases["челябинска область"] == "74"


def test_diseases_cover_report_names_without_unsupported_recommendations():
    diseases = read_yaml("diseases.yaml")
    assert len({row["slug"] for row in diseases}) == len(diseases)
    aliases = {}
    for row in diseases:
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", row["slug"])
        assert row["species"] and set(row["species"]) <= SPECIES
        assert isinstance(row["is_zoonosis"], bool)
        assert 1 <= row["base_level"] <= 5
        assert row["description"]
        for alias in [row["name"], *row["aliases"]]:
            normalized = alias.casefold().replace("ё", "е")
            assert aliases.get(normalized, row["slug"]) == row["slug"]
            aliases[normalized] = row["slug"]
        for recommendation in row["recommendations"]:
            assert recommendation["text"]
            assert urlparse(recommendation["source_url"]).scheme == "https"
    for name in [
        "Бешенство животных",
        "Бруцеллёз КРС",
        "Лейкоз КРС",
        "Трихинеллёз",
        "Эмфизематозный кабункул (Эмкар)",
        "Лептоспироз собаки",
        "Случная болезнь лошадей",
        "Варроатоз пчёл",
    ]:
        assert name.casefold().replace("ё", "е") in aliases


def test_offers_have_safe_filters_and_official_product_links():
    offers = read_yaml("offers.yaml")
    assert len({row["id"] for row in offers}) == len(offers) >= 4
    for row in offers:
        assert row["title"] and row["description"]
        assert urlparse(row["url"]).hostname in {
            "svoefermerstvo.ru",
            "www.rshb.ru",
            "rshbins.ru",
            "www.rshbins.ru",
        }
        assert row["source_url"] == row["url"]
        assert row["verified_at"]
        assert 0 <= row["min_level"] <= 5
        assert set(row["species"]) <= SPECIES
        assert isinstance(row["requires_quarantine"], bool)
        assert isinstance(row["requires_zoonosis"], bool)


def test_common_diseases_have_sourced_actions_and_observable_signs():
    diseases = {row["slug"]: row for row in read_yaml("diseases.yaml")}
    required = {
        "rabies",
        "brucellosis",
        "leukosis",
        "leptospirosis",
        "trichinellosis",
        "african-swine-fever",
        "avian-influenza",
        "anthrax",
    }
    for slug in required:
        row = diseases[slug]
        assert row["recommendations"], f"{slug}: отсутствует проверенное действие"
        assert row.get("symptoms"), f"{slug}: отсутствуют проверенные признаки"
        assert all(isinstance(sign, str) and sign.strip() for sign in row["symptoms"])
        assert row.get("symptom_source_urls"), f"{slug}: нет источника признаков"
        rule = row["guidance_rule"]
        verified = date.fromisoformat(row["guidance_verified_at"])
        assert date.fromisoformat(rule["date"]) <= verified
        if rule.get("valid_from"):
            assert date.fromisoformat(rule["valid_from"]) <= verified
        if rule.get("valid_until"):
            assert date.fromisoformat(rule["valid_until"]) > verified
        assert row["symptoms_note"]
        urls = [r["source_url"] for r in row["recommendations"]]
        urls.extend(row["symptom_source_urls"])
        for url in urls:
            host = urlparse(url).hostname or ""
            assert host in {"publication.pravo.gov.ru", "pravo.gov.ru"} or host.endswith(
                "fsvps.gov.ru"
            )


def test_geometry_and_neighbors_are_consistent_without_point_contacts():
    path = DATA / "regions.geojson"
    assert path.exists(), "Отсутствует геометрия регионов"
    collection = json.loads(path.read_text())
    assert collection["type"] == "FeatureCollection"
    assert collection["license"] and collection["sources"]
    regions = {row["code"]: row for row in read_yaml("regions.yaml")}
    geometries = {}
    for feature in collection["features"]:
        code = feature["properties"]["code"]
        assert code in regions and code not in geometries
        geometry = shape(feature["geometry"])
        assert geometry.is_valid and not geometry.is_empty
        assert geometry.geom_type in {"Polygon", "MultiPolygon"}
        geometries[code] = geometry
    assert len(geometries) == 89
    for code, row in regions.items():
        for neighbor in row["neighbors"]:
            assert code in regions[neighbor]["neighbors"]
            shared = geometries[code].boundary.intersection(geometries[neighbor].boundary)
            assert shared.length > 0, f"{code}/{neighbor}: нет общей границы"
    # Два известных сухопутных контакта: столица и область, Тула и Калуга.
    assert "50" in regions["77"]["neighbors"]
    assert "40" in regions["71"]["neighbors"]


def test_archive_names_have_unambiguous_reference_matches():
    regions = read_yaml("regions.yaml")
    diseases = read_yaml("diseases.yaml")
    region_names = {
        n.casefold().replace("ё", "е") for r in regions for n in [r["name"], *r["aliases"]]
    }
    disease_names = {
        n.casefold().replace("ё", "е") for d in diseases for n in [d["name"], *d["aliases"]]
    }
    assert "республика северная осетия" in region_names
    for name in [
        "Пастереллёз животных",
        "Бруцеллёз собаки",
        "Лептоспироз свиней",
        "Хламидиоз птиц (орнитоз)",
    ]:
        assert name.casefold().replace("ё", "е") in disease_names
