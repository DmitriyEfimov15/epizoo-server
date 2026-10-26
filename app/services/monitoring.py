from datetime import date, timedelta

from app.core.errors import not_found
from app.core.time import today_moscow
from app.models import Event, Quarantine
from app.repositories.monitoring import fetch_snapshot
from app.schemas.api import SPECIES, EventOut, MapRegion, QuarantineOut, RegionOut


class Monitor:
    def __init__(self, snapshot: dict, today: date | None = None):
        self.today = today or today_moscow()
        self.regions = {r.code: r for r in snapshot["regions"]}
        self.diseases = {d.id: d for d in snapshot["diseases"]}
        self.by_slug = {d.slug: d for d in self.diseases.values()}
        self.events = snapshot["events"]
        self.by_event = {e.id: e for e in self.events}
        self.quarantines = snapshot["quarantines"]
        self.neighbors = {code: [] for code in self.regions}
        for row in snapshot["neighbors"]:
            self.neighbors[row.region_code].append(row.neighbor_code)
        self.weekly_counts = snapshot["weekly_counts"]
        self.news = snapshot["news"]
        self.reports = snapshot["reports"]

    @classmethod
    async def load(cls, session):
        return cls(await fetch_snapshot(session))

    def region(self, code):
        if code not in self.regions:
            raise not_found("Регион не найден")
        return self.regions[code]

    def check_filters(self, species=None, disease=None):
        if species and species not in SPECIES:
            raise not_found("Вид животных не найден")
        if disease and disease not in self.by_slug:
            raise not_found("Болезнь не найдена")

    def matches(self, event: Event, species=None, disease=None):
        kinds = [species] if isinstance(species, str) else species
        return (
            not kinds
            or bool(set(kinds) & set(event.species or self.diseases[event.disease_id].species))
        ) and (not disease or self.diseases[event.disease_id].slug == disease)

    def selected_events(
        self, code=None, species=None, disease=None, start=None, end=None, kind=None
    ):
        return sorted(
            [
                e
                for e in self.events
                if (not code or e.region_code == code)
                and (not start or e.date >= start)
                and (not end or e.date <= end)
                and (not kind or e.kind == kind)
                and self.matches(e, species, disease)
            ],
            key=lambda e: (e.date, e.id),
            reverse=True,
        )

    def effective_status(self, quarantine: Quarantine):
        if quarantine.status == "active" and (self.today - quarantine.since).days >= 90:
            return "unconfirmed"
        return quarantine.status

    def selected_quarantines(self, code, species=None, disease=None):
        return [
            q
            for q in self.quarantines
            if q.region_code == code
            and q.since <= self.today
            and self.effective_status(q) != "lifted"
            and self.matches(self.by_event[q.set_event_id], species, disease)
        ]

    def event_out(self, event):
        disease = self.diseases[event.disease_id]
        fields = {
            name: getattr(event, name) for name in EventOut.model_fields if hasattr(event, name)
        }
        return EventOut(**fields, disease_slug=disease.slug, disease_name=disease.name)

    def quarantine_out(self, quarantine):
        event = self.by_event[quarantine.set_event_id]
        disease = self.diseases[quarantine.disease_id]
        return QuarantineOut(
            id=quarantine.id,
            set_event_id=event.id,
            disease_id=disease.id,
            disease_slug=disease.slug,
            disease_name=disease.name,
            region_code=quarantine.region_code,
            locality=event.locality,
            species=event.species,
            status=self.effective_status(quarantine),
            since=quarantine.since,
            until=quarantine.until,
            level=event.level,
            source_urls=event.source_urls,
        )

    def map_region(self, code, species=None, disease=None, period=30):
        self.region(code)
        self.check_filters(species if isinstance(species, str) else None, disease)
        start = self.today - timedelta(days=period - 1)
        events = self.selected_events(code, species, disease, start, self.today)
        quarantines = self.selected_quarantines(code, species, disease)
        levels = [e.level for e in events if e.kind != "quarantine_lifted"] + [
            self.by_event[q.set_event_id].level for q in quarantines
        ]
        return MapRegion(
            code=code,
            name=self.regions[code].name,
            level=max(levels, default=0),
            event_count=len(events),
            active_quarantine_count=sum(self.effective_status(q) == "active" for q in quarantines),
            unconfirmed_quarantine_count=sum(
                self.effective_status(q) == "unconfirmed" for q in quarantines
            ),
        )

    def region_out(self, code, species=None, disease=None, period=30):
        data = self.map_region(code, species, disease, period)
        return RegionOut(
            **data.model_dump(),
            quarantines=[
                self.quarantine_out(q) for q in self.selected_quarantines(code, species, disease)
            ],
            events=[
                self.event_out(e)
                for e in self.selected_events(
                    code, species, disease, self.today - timedelta(days=period - 1), self.today
                )
            ],
            neighbors=[
                self.map_region(n, species, disease, period) for n in sorted(self.neighbors[code])
            ],
        )

    def recommendations(self, events):
        items = []
        for disease_id in sorted({e.disease_id for e in events}):
            for advice in self.diseases[disease_id].recommendations:
                if advice not in items:
                    items.append(advice)
        return items
