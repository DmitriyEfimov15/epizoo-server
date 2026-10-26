import math


def level_from_score(total: float | None, base_level: int) -> int:
    value = base_level if total is None or not math.isfinite(total) else math.ceil(total)
    return min(5, max(1, value))
