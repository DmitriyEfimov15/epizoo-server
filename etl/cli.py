"""Управление загрузкой: python -m etl.cli backfill/update/reconcile/load-cache."""

import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.time import today_moscow
from app.db.seed import seed_reference_data
from app.db.session import make_engine, session_factory
from app.services.quarantine import rebuild_quarantines
from etl.fetch import ReportRef, fetch_index, fetch_since, make_client
from etl.load import load_report, run_update
from etl.reconcile import reconcile

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


async def execute(args):
    settings = Settings()
    if args.command == "fetch":
        downloaded = await fetch_since(args.since, args.cache_dir, refresh=False)
        return {"cached_reports": len(downloaded), "issues": downloaded.issues}
    if args.command in ("backfill", "update"):
        since = args.since if args.command == "backfill" else None
        return await run_update(settings, since, args.cache_dir)
    engine = make_engine(settings.database_url)
    try:
        async with session_factory(engine)() as session:
            if args.command == "reconcile":
                return {"differences": await reconcile(session)}
            await seed_reference_data(session, settings.data_dir)
            if args.manifest:
                raw = json.loads(args.manifest.read_text())
                refs = [
                    ReportRef(
                        published=date.fromisoformat(r["published"]),
                        kind=r["kind"],
                        url=r["url"],
                        title=r["title"],
                        period_from=date.fromisoformat(r["period_from"])
                        if r.get("period_from")
                        else None,
                        period_to=date.fromisoformat(r["period_to"])
                        if r.get("period_to")
                        else None,
                    )
                    for r in raw
                ]
            else:
                async with make_client() as client:
                    refs = await fetch_index(client)
            result = {
                "reports": 0,
                "events": 0,
                "weekly_counts": 0,
                "skipped": 0,
                "partial": 0,
                "issues": [],
            }
            for ref in sorted(refs, key=lambda r: r.published):
                path = args.cache_dir / ref.filename
                if not path.exists():
                    continue
                item = await load_report(session, ref, path)
                for key, value in item.items():
                    if key == "issues":
                        result[key].extend(f"{path.name}: {warning}" for warning in value)
                    else:
                        result[key] += value
            await rebuild_quarantines(session, today_moscow())
            await session.commit()
            return result
    finally:
        await engine.dispose()


def main():
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    parser = argparse.ArgumentParser(prog="etl")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="скачать PDF в кэш")
    fetch.add_argument(
        "--since", type=date.fromisoformat, default=today_moscow() - timedelta(days=365)
    )
    backfill = commands.add_parser("backfill", help="загрузить доступную историю за год")
    backfill.add_argument(
        "--since", type=date.fromisoformat, default=today_moscow() - timedelta(days=365)
    )
    commands.add_parser("update", help="обновить последние публикации и RSS")
    commands.add_parser("reconcile", help="сверить дневные события и еженедельные счётчики")
    cached = commands.add_parser("load-cache", help="загрузить уже скачанные PDF")
    cached.add_argument("--manifest", type=Path, help="JSON списка сводок для автономного запуска")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
