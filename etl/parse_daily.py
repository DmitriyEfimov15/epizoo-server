"""Автомат ежедневных сводок: заголовок → регионы → общая оценка → сноски."""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pymupdf

from etl.normalize import clean_text, disease_heading, extract_species, ignored_section


@dataclass
class ParsedEvent:
    disease: str
    region: str
    district: str | None
    locality: str | None
    species: list[str]
    kind: str
    text: str
    scores: list[int]
    total: float | None
    source_urls: list[str]
    date: date


@dataclass
class ParseResult:
    events: list[ParsedEvent] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class _RegionBlock:
    region: str
    refs: list[int]
    page: int
    lines: list[str] = field(default_factory=list)


@dataclass
class _DiseaseBlock:
    disease: str
    kind: str
    page: int
    regions: list[_RegionBlock] = field(default_factory=list)
    scores: list[int] = field(default_factory=list)
    total: float | None = None


def pdf_lines(path: Path) -> list[tuple[int, str]]:
    """Пропускает колонтитулы, сохраняя номера страниц и переносы текста."""
    lines = []
    with pymupdf.open(path) as document:
        for number, page in enumerate(document, 1):
            footer = False
            for raw in page.get_text(sort=True).splitlines():
                line = clean_text(raw)
                if re.match(
                    r"^(?:ИНФОРМАЦИОННО-АНАЛИТИЧЕСК|УПРАВЛЕНИЯ ВЕТНАДЗОРА|"
                    r"ЭПИЗООТИЧЕСКАЯ СИТУАЦИЯ|РОССИ[ЙИ]СКО[ЙИ] ФЕД[ЕА]РАЦИИ|"
                    r"\d{1,2}\s+[а-я]+\s+202\d\s*(?:год[а]?|г\.)?$|"
                    r"\d{2}\.\d{2}.*202\d\s*(?:год[а]?|г\.)?$)",
                    line,
                ):
                    continue
                if line.startswith("600901"):
                    footer = True
                if footer or not line or line.startswith(("Информация по сообщениям", "Сводное")):
                    continue
                lines.append((number, line))
    return lines


def _parse_date(text: str) -> date | None:
    match = re.search(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(20\d{2})(?!\d)", text)
    if not match:
        words = re.search(r"(\d{1,2})\s+([а-я]+)\s+(20\d{2})(?!\d)", text.lower())
        months = (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        )
        if not words or words[2] not in months:
            return None
        try:
            return date(int(words[3]), months.index(words[2]) + 1, int(words[1]))
        except ValueError:
            return None
    try:
        return date(int(match[3]), int(match[2]), int(match[1]))
    except ValueError:
        return None


def _footnotes(lines: list[tuple[int, str]]) -> dict[int, tuple[str, date | None]]:
    notes: dict[int, tuple[str, date | None]] = {}
    pending: int | None = None
    text = ""

    def save():
        if pending is None:
            return
        match = re.search(r"https?://\S+", text)
        if match:
            url = match[0].rstrip(".,;")
            notes[pending] = (url, _parse_date(text[match.end() :]))

    for _, line in lines:
        match = re.match(r"^(\d+)\s*URL\s*:?\s*(.*)", line, re.I)
        if match:
            save()
            pending, text = int(match[1]), match[2]
        elif pending is not None and (
            not _parse_date(text)
            and not disease_heading(line)
            and not re.match(r"[➢•]|ОЦЕНКА|ИТОГ|Оценка", line)
        ):
            text += line if text.endswith(("-", "/")) else " " + line
        else:
            save()
            pending = None
    save()
    return notes


# Обозначение + имя с заглавной буквы: не путает «г.» в датах и «с.» в ссылках.
_LOCALITY = re.compile(
    r"(?<!\w)(?:р\.?\s*п\.?|пгт\.?|птг\.?|ст-ца\.?|станиц[аые]|"
    r"пос[.]|посел(?:ок|ка|ке)|город(?:а|е)?|село|села|селе|"
    r"дерев(?:ня|ни|не)|сельского поселения|поселка городского типа|"
    r"дер[.]|хут[.,]|хутор(?:а|е)?|[сдпгх][.])\s+[\"«]?"
    r"([А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9-]*(?:\s+[А-ЯЁ][А-Яа-яЁё-]*)*)"
)
_DISTRICT = re.compile(
    r"(?:[А-ЯЁ][а-яё-]+(?:\s+(?:муниципальный|муниципального|городской))?\s+"
    r"(?:район[а]?|округ[а]?|м\.о\.|г\.о\.)|"
    r"(?:городской округ|м\.о\.)\s+[А-ЯЁ][а-яё-]+)"
)


def _places(text: str) -> list[tuple[str | None, str | None, str]]:
    """Один адрес — одно событие, списки пунктов разбираются независимо от строк PDF."""
    lines = text.splitlines()
    if len(lines) > 1 and (_LOCALITY.match(lines[0]) or _DISTRICT.match(lines[0])):
        entries = [lines[0]]
        for line in lines[1:]:
            if entries[-1].endswith(".") and (_LOCALITY.match(line) or _DISTRICT.match(line)):
                entries.append(line)
            else:
                entries[-1] += " " + line
        if len(entries) > 1:
            return [place for entry in entries for place in _places(entry)]
    bullets = re.split(r"\s+-\s+", text)
    if len(bullets) > 1:
        return [place for bullet in bullets[1:] for place in _places(bullet)]
    relative = re.search(
        r"\b(?:на расстоянии\s+)?\d+(?:[.,]\d+)?\s*(?:км|м|километр\w*|метр\w*)\s+"
        r"(?:на\s+|[а-яё-]*(?:нее|ней)|от\s+)",
        text,
    )
    if relative:
        address = text[relative.start() :].rstrip(";. ")
        district = _DISTRICT.search(address)
        return [(address, district[0] if district else None, text)]
    matches = list(_LOCALITY.finditer(text))
    # Город в адресе «г. Кинель, п. Лебедь» — родитель поселка, не отдельный очаг.
    matches = [
        match
        for i, match in enumerate(matches)
        if not (
            match[0].startswith(("г.", "город"))
            and i + 1 < len(matches)
            and re.fullmatch(r"\s*,\s*", text[match.end() : matches[i + 1].start()])
        )
    ]
    if not matches:
        district = _DISTRICT.search(text)
        return [(None, district[0] if district else None, text)]
    districts = list(_DISTRICT.finditer(text))
    result = []
    for index, match in enumerate(matches):
        start = matches[index - 1].end() if index else 0
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        nearest = [d for d in districts if start <= d.start() < end]
        district = min(nearest, key=lambda d: abs(d.start() - match.start())) if nearest else None
        if district is None:
            same_sentence = []
            for candidate in districts:
                between = text[
                    min(candidate.end(), match.end()) : max(candidate.start(), match.start())
                ]
                between = re.sub(r"\b(?:[сдпгх]|пос|дер|м\.о|г\.о)\.", "", between)
                if not re.search(r"\.\s+[А-ЯЁ]", between):
                    same_sentence.append(candidate)
            if same_sentence:
                district = min(same_sentence, key=lambda d: abs(d.start() - match.start()))
        # Сохраняем только вид конкретного пункта, не соседнего адреса.
        snippet = text[match.start() : end]
        locality = match[1]
        for administrative in _DISTRICT.finditer(locality + " " + text[match.end() : end]):
            if administrative.start() < len(locality):
                locality = locality[: administrative.start()].strip()
                break
        result.append((locality, district[0] if district else None, snippet))
    return result


def parse_daily(path: Path, report_date: date) -> ParseResult:
    result = ParseResult()
    try:
        lines = pdf_lines(path)
    except Exception as exc:
        result.issues.append(f"Не удалось прочитать PDF {path.name}: {exc}")
        return result
    notes = _footnotes(lines)
    blocks: list[_DiseaseBlock] = []
    current: _DiseaseBlock | None = None
    scoring = False
    footnote = False
    previous_page = 0
    for page, line in lines:
        if re.match(r"\d+\s*URL\b", line, re.I):
            footnote = True
            continue
        if footnote:
            # После сносок начинается следующая страница; колонтитул уже удалён.
            if page == previous_page:
                continue
            footnote = False
        previous_page = page
        if ignored_section(line):
            current = None
            scoring = False
            continue
        heading = disease_heading(line)
        if heading:
            current = _DiseaseBlock(*heading, page)
            blocks.append(current)
            scoring = False
            continue
        region = re.match(r"^[➢•]\s*(.+?)([\d,\s]*)\s*:?$", line)
        if region:
            if current is None:
                continue
            current.regions.append(
                _RegionBlock(
                    region[1].rstrip(":"),
                    [int(n) for n in re.findall(r"\d+", region[2])],
                    page,
                )
            )
            scoring = False
            continue
        if current is None:
            continue
        if line.startswith("Оценка значимости"):
            scoring = True
            continue
        if line.startswith("ОЦЕНКА"):
            scoring = True
            current.scores = [int(n) for n in re.findall(r"\d+", line.partition(":")[2])]
            if len(current.scores) != 6:
                result.issues.append(f"Страница {page}: неполная оценка {current.disease}")
            continue
        if line.startswith("ИТОГ"):
            match = re.search(r":\s*(\d+(?:[.,]\d+)?)\s*$", line)
            if match:
                current.total = float(match[1].replace(",", "."))
            else:
                result.issues.append(f"Страница {page}: не распознан итог {current.disease}")
            scoring = True
            continue
        if scoring and current.total is not None:
            result.issues.append(f"Страница {page}: не распознана новая секция: {line}")
            current = None
            scoring = False
            continue
        if not scoring and current.regions:
            current.regions[-1].lines.append(line)

    for block in blocks:
        if block.regions and (len(block.scores) != 6 or block.total is None):
            result.issues.append(
                f"Страница {block.page}: отсутствует полная оценка {block.disease}"
            )
        for region in block.regions:
            text = clean_text(" ".join(region.lines))
            if not text:
                result.issues.append(f"Страница {region.page}: пустой блок {region.region}")
                continue
            places = _places("\n".join(region.lines))
            if any(
                locality and re.search(r"\d+\s*(?:км|м|километр|метр)", locality)
                for locality, _, _ in places
            ):
                result.issues.append(
                    f"Страница {region.page}: границы очага заданы относительно населённого "
                    f"пункта, адрес сохранён полностью: {region.region}"
                )
            if any(locality is None for locality, _, _ in places):
                result.issues.append(
                    f"Страница {region.page}: не выделен населённый пункт {region.region}, "
                    "текст события сохранён"
                )
            refs = [notes[n] for n in region.refs if n in notes]
            if len(refs) != len(region.refs):
                result.issues.append(f"Страница {region.page}: не найдены сноски {region.region}")
            # Даты актов в вводной части имеют приоритет над датой публикации ссылки.
            intro = text.split("на отдельных территориях")[0]
            act_dates = {
                value
                for match in re.finditer(r"\bот\s+([^№;]{1,60})", intro)
                if (value := _parse_date(match[1])) is not None
            }
            act_date = next(iter(act_dates)) if len(act_dates) == 1 else None
            one_to_one = len(refs) == len(places)
            if not one_to_one and len(refs) > 1:
                result.issues.append(
                    f"Страница {region.page}: неоднозначное соответствие пунктов и сносок "
                    f"{region.region}: {len(places)} / {len(refs)}"
                )
            kind = block.kind
            explicit_set = re.search(r"установлены\s+ограничительные\s+мероприятия", text, re.I)
            explicit_lift = re.search(r"отменены\s+ограничительные\s+мероприятия", text, re.I)
            if bool(explicit_set) != bool(explicit_lift):
                actual_kind = "quarantine_set" if explicit_set else "quarantine_lifted"
                if actual_kind != kind:
                    result.issues.append(
                        f"Страница {region.page}: заголовок противоречит тексту акта "
                        f"{region.region}, {block.disease}"
                    )
                kind = actual_kind
            if (
                kind != "quarantine_lifted"
                and not refs
                and not re.search(
                    r"карантин|ограничительн",
                    text,
                    re.I,
                )
            ):
                kind = "outbreak"
            for index, (locality, district, snippet) in enumerate(places):
                sources = [refs[index]] if one_to_one else refs
                dates = {source[1] for source in sources if source[1] is not None}
                event_date = act_date or (next(iter(dates)) if len(dates) == 1 else report_date)
                species = extract_species(snippet) or extract_species(block.disease)
                result.events.append(
                    ParsedEvent(
                        block.disease,
                        region.region,
                        district,
                        locality,
                        species,
                        kind,
                        text,
                        list(block.scores),
                        block.total,
                        [source[0] for source in sources],
                        event_date,
                    )
                )
    if not result.events:
        result.issues.append("Страница 1: в PDF не распознаны события ежедневной сводки")
    return result
