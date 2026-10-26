"""Независимые недельные счётчики населённых пунктов из сводок ИАЦ."""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from etl.normalize import disease_heading, extract_species, ignored_section
from etl.parse_daily import pdf_lines


@dataclass
class ParsedCount:
    disease: str
    region: str
    species: list[str]
    kind: str
    count: int


@dataclass
class WeeklyParseResult:
    counts: list[ParsedCount] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def parse_weekly(path: Path, week_start: date) -> WeeklyParseResult:
    result = WeeklyParseResult()
    try:
        lines = pdf_lines(path)
    except Exception as exc:
        result.issues.append(f"Не удалось прочитать PDF {path.name}: {exc}")
        return result
    heading = None
    for page, line in lines:
        found = disease_heading(line)
        if found:
            heading = found
            continue
        if ignored_section(line):
            heading = None
            continue
        match = re.match(r"^(\d+)\s*н\s*\.\s*п\s*\.?\s*[–—-]\s*(.+)", line)
        if match:
            if heading is None:
                result.issues.append(f"Страница {page}: счётчик без заголовка: {line}")
                continue
            disease, kind = heading
            region = match[2].rstrip(".,; ")
            species_text = re.search(r"/(.*?)/", region)
            species = extract_species(species_text[1]) if species_text else extract_species(disease)
            region = re.sub(r"\s*/.*?/[.,; ]*", "", region).strip()
            result.counts.append(ParsedCount(disease, region, species, kind, int(match[1])))
        elif re.match(r"\d+\s*н", line):
            result.issues.append(f"Страница {page}: не распознан недельный счётчик: {line}")
    if not result.counts:
        result.issues.append("Страница 1: в PDF не распознаны недельные счётчики")
    return result
