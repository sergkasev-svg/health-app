"""
Фильтр галлюцинаций: отсекает нерелевантные и опасные диагнозы из выдачи пользователю.
Используется после генерации гипотез в diagnostic_ranking_engine и в lab postprocess.
"""


BLOCK_BY_LAB_TYPE = {
    "organic_acids": [
        "инфекция",
        "цистит",
        "уретрит",
        "пневмония",
        "covid",
        "отит",
        "пиелонефрит",
        "мигрен",
        "гистамин",
        "непереносимость гистамина",
        "пищевая аллергия",
        "липид",
        "холестер",
        "ldl",
        "бессонниц",
        "инсомни",
        "анемия",
        "железодефицит",
        "кортизол",
    ],
}

HARDBLOCK = [
    "малярия",
    "сепсис",
    "covid",
    "covid-19",
    "импетиго",
    "отит",
    "инсомния",
]


def is_allowed_for_lab_type(name: str, lab_type: str | None) -> bool:
    """Проверяет, разрешён ли диагноз для данного типа анализа."""
    if not lab_type or lab_type == "unknown":
        return True
    blocked = BLOCK_BY_LAB_TYPE.get(lab_type, [])
    if not blocked:
        return True
    low = (name or "").lower()
    return not any(b in low for b in blocked)


def is_relevant_diagnosis(name: str, probability: float, context: dict) -> bool:
    name = (name or "").strip().lower()
    if not name:
        return False

    if name in HARDBLOCK or any(block in name for block in HARDBLOCK):
        return False

    lab_type = context.get("lab_type")
    if not is_allowed_for_lab_type(name, lab_type):
        return False

    if probability < 0.3:
        return False

    symptoms = " ".join(context.get("symptoms", []) or []).lower()
    if not isinstance(context.get("symptoms"), list):
        symptoms = str(context.get("symptoms", "") or "").lower()

    severe = ["сепсис", "менингит", "инфаркт", "инсульт"]

    if any(x in name for x in severe) and not symptoms:
        return False

    return True
