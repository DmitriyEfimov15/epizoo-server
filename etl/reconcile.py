from collections import Counter

from sqlalchemy import select

from app.models import Event, Report, WeeklyCount


def compare_counts(reports, events, weekly_counts):
    report_dates = {
        r.id: r.date for r in reports if r.type == "daily" and getattr(r, "is_current", True)
    }
    weeks = {(c.week_start, c.week_end) for c in weekly_counts}
    result = []
    for start, end in sorted(weeks):
        observed = Counter(
            (
                e.disease_id,
                e.region_code,
                "quarantine_lifted" if e.kind == "quarantine_lifted" else "quarantine_set",
            )
            for e in events
            if e.report_id in report_dates and start <= report_dates[e.report_id] <= end
        )
        expected = Counter()
        for row in weekly_counts:
            if row.week_start == start and row.week_end == end:
                expected[(row.disease_id, row.region_code, row.kind)] += row.count
        for key in sorted(observed.keys() | expected.keys()):
            if observed[key] != expected[key]:
                disease, region, kind = key
                result.append(
                    {
                        "week_start": start.isoformat(),
                        "week_end": end.isoformat(),
                        "disease_id": disease,
                        "region_code": region,
                        "kind": kind,
                        "daily_count": observed[key],
                        "weekly_count": expected[key],
                        "difference": observed[key] - expected[key],
                    }
                )
    return result


async def reconcile(session):
    reports = (await session.scalars(select(Report).where(Report.is_current.is_(True)))).all()
    events = (await session.scalars(select(Event))).all()
    weekly = (await session.scalars(select(WeeklyCount))).all()
    return compare_counts(reports, events, weekly)
