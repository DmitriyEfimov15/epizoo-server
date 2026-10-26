from pathlib import Path

import yaml

from app.schemas.api import OfferOut


def select_offers(monitor, code, species=None, data_dir: Path | None = None):
    region = monitor.map_region(code, species)
    path = (data_dir or Path(__file__).resolve().parents[2] / "data") / "offers.yaml"
    if not path.exists():
        return []
    rules = yaml.safe_load(path.read_text()) or []
    quarantines = monitor.selected_quarantines(code, species)
    zoonosis = any(monitor.diseases[q.disease_id].is_zoonosis for q in quarantines)
    result = []
    for rule in rules:
        if region.level < rule.get("min_level", 0):
            continue
        if rule.get("species") and species and species not in rule["species"]:
            continue
        if rule.get("requires_quarantine") and not quarantines:
            continue
        if rule.get("requires_zoonosis") and not zoonosis:
            continue
        result.append(OfferOut(**{key: rule[key] for key in OfferOut.model_fields}))
    return result
