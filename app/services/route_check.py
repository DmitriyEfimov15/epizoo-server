from app.schemas.api import RouteResult


def check_route(monitor, from_code, to_code, species):
    monitor.check_filters(species)
    departure = monitor.region_out(from_code, species)
    arrival = monitor.region_out(to_code, species)
    level = max(departure.level, arrival.level)
    return RouteResult(
        from_region=departure,
        to_region=arrival,
        species=species,
        verdict="high" if level >= 4 else "elevated" if level >= 2 else "low",
        checklist=[
            (
                "Уточнить действующие ограничения у государственной ветеринарной службы "
                "отправления и назначения."
            ),
            "Проверить условия перевозки в официальном сервисе «Цербер».",
            (
                "Согласовать ветеринарные сопроводительные документы и необходимые "
                "обследования с ветслужбой."
            ),
        ],
        official_url="https://cerberus.vetrf.ru/cerberus/transit/checkPath/pub",
        disclaimer=(
            "Результат справочный и не заменяет решение государственной ветеринарной "
            "службы. Не является разрешением на перевозку."
        ),
    )
