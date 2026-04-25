"""
Динамика по маркерам: сравнение последних двух значений (тренд вверх/вниз/стабильно).
Для подписки: «Михаил показывает, что меняется».
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models import MarkerSnapshot

TREND_UP = "up"
TREND_DOWN = "down"
TREND_STABLE = "stable"
TREND_UNKNOWN = "unknown"

# Маркеры для трендов по умолчанию (dashboard, sample_product_copy.json)
RECOMMENDED_MARKERS_FOR_TRENDS = [
    "ldl",
    "cholesterol_total",
    "hb",
    "esr",
    "alt",
    "ast",
    "ferritin",
    "vitamin_d",
]


def _to_float(s: Any) -> float | None:
    try:
        if s is None or s == "":
            return None
        return float(str(s).replace(",", "."))
    except Exception:
        return None


def compare_latest_two(
    db: Session,
    user_id: int,
    marker_key: str,
) -> Dict[str, Any]:
    rows = (
        db.query(MarkerSnapshot)
        .filter(
            MarkerSnapshot.user_id == user_id,
            MarkerSnapshot.marker_key == marker_key,
        )
        .order_by(MarkerSnapshot.created_at.desc())
        .limit(2)
        .all()
    )
    if len(rows) < 2:
        return {
            "marker_key": marker_key,
            "trend": TREND_UNKNOWN,
            "message": "Недостаточно данных для динамики.",
        }
    current = _to_float(rows[0].marker_numeric or rows[0].marker_value)
    previous = _to_float(rows[1].marker_numeric or rows[1].marker_value)
    if current is None or previous is None:
        return {
            "marker_key": marker_key,
            "trend": TREND_UNKNOWN,
            "message": "Нет двух числовых значений для сравнения.",
        }
    delta = current - previous
    if abs(delta) < 1e-9:
        trend = TREND_STABLE
        msg = f"{marker_key}: без заметной динамики."
    elif delta > 0:
        trend = TREND_UP
        msg = f"{marker_key}: показатель вырос на {delta:.2f}."
    else:
        trend = TREND_DOWN
        msg = f"{marker_key}: показатель снизился на {abs(delta):.2f}."
    return {
        "marker_key": marker_key,
        "current": current,
        "previous": previous,
        "delta": round(delta, 4),
        "trend": trend,
        "message": msg,
    }


def build_dynamics_summary(
    db: Session,
    user_id: int,
    marker_keys: List[str],
) -> Dict[str, Any]:
    items = [compare_latest_two(db, user_id, key) for key in marker_keys]
    texts = [x["message"] for x in items if x.get("message")]
    return {"items": items, "text": "\n".join(f"- {t}" for t in texts)}
