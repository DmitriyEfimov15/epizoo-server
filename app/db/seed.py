from pathlib import Path

import yaml
from sqlalchemy import select

from app.core.config import ROOT
from app.models import Disease, Region, RegionNeighbor


async def seed_reference_data(session, data_dir: Path | None = None):
    data_dir = data_dir or ROOT / "data"
    region_data = yaml.safe_load((data_dir / "regions.yaml").read_text())
    for item in region_data:
        region = await session.get(Region, str(item["code"]))
        fields = {
            key: item.get(key, [] if key == "aliases" else "")
            for key in ("name", "aliases", "federal_district")
        }
        if region is None:
            session.add(Region(code=str(item["code"]), **fields))
        else:
            for key, value in fields.items():
                setattr(region, key, value)
    await session.flush()
    existing = {
        (r.region_code, r.neighbor_code)
        for r in (await session.scalars(select(RegionNeighbor))).all()
    }
    for item in region_data:
        for neighbor in item.get("neighbors", []):
            edge = (str(item["code"]), str(neighbor))
            if edge not in existing:
                session.add(RegionNeighbor(region_code=edge[0], neighbor_code=edge[1]))
                existing.add(edge)
    for item in yaml.safe_load((data_dir / "diseases.yaml").read_text()):
        disease = await session.scalar(select(Disease).where(Disease.slug == item["slug"]))
        fields = {
            key: item.get(key, [])
            for key in (
                "name",
                "aliases",
                "species",
                "is_zoonosis",
                "base_level",
                "description",
                "recommendations",
                "symptoms",
            )
        }
        if disease is None:
            session.add(Disease(slug=item["slug"], **fields))
        else:
            for key, value in fields.items():
                setattr(disease, key, value)
    await session.flush()
