"""
SearchService backend helper: lightweight smart suggestions for symptoms/features.
"""
from typing import Any

SUGGESTIONS = [
    "головная боль",
    "температура",
    "кашель",
    "повышенное давление",
    "гипертония",
    "анемия",
    "дефицит витамина D",
    "бессонница",
    "стресс и переутомление",
    "питание при усталости",
    "физическая активность",
    "анализы крови",
    "синдром жильбера",
    "повышенный билирубин",
    "желтушность склер",
    "боль в правом подреберье",
    "темная моча и светлый стул",
    "печеночные пробы",
    "обильные месячные",
    "выпадение волос",
    "нерегулярный цикл",
    "прыщи и гормоны",
    "боль в груди и одышка",
    "тревога и сердцебиение",
    "температура 39 и боль в горле",
    "кашель с мокротой",
    "хроническая усталость",
    "дефицит железа",
    "дефицит B12",
    "дефицит магния",
    "плохой сон и стресс",
    "вздутие живота",
    "проблемы с пищеварением",
    "геморрой и кровь",
    "кровь в стуле",
    "боль при мочеиспускании",
    "боль в колене после травмы",
    "сколиоз у подростка",
    "аменорея",
    "выделения из груди",
    "послеродовая депрессия",
]


def suggest(query: str, limit: int = 8) -> list[str]:
    q = (query or "").lower().strip()
    if len(q) < 1:
        return []
    prefix: list[str] = []
    contains: list[str] = []
    token_prefix: list[str] = []
    for s in SUGGESTIONS:
        low = s.lower()
        if low.startswith(q):
            prefix.append(s)
            continue
        if any(tok.startswith(q) for tok in low.split()):
            token_prefix.append(s)
            continue
        if q in low:
            contains.append(s)
    ordered = prefix + token_prefix + contains
    # Stable dedupe while preserving score order.
    out: list[str] = []
    seen: set[str] = set()
    for s in ordered:
        k = s.lower().strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= limit:
            break
    return out

