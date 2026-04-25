"""Построение гипотез по маркерам и симптомам (AUTO DIAGNOSIS ENGINE)."""


def build_hypotheses(payload):
    m = payload.get("lab_markers", {})
    symptoms = " ".join(payload.get("symptoms", [])).lower()

    out = []

    if m.get("pyroglutamic") == "high":
        out.append({
            "id": "oxidative_stress",
            "label": "Окислительный стресс",
            "meaning": "может снижать восстановление и энергию"
        })

    if m.get("malonic") == "high" or m.get("sebacic") == "high":
        out.append({
            "id": "energy_issue",
            "label": "Нарушение энергообмена",
            "meaning": "энергия может вырабатываться менее эффективно"
        })

    if m.get("figlu") == "high":
        out.append({
            "id": "vitamin_deficit",
            "label": "Возможный дефицит B9/B12",
            "meaning": "может влиять на энергию и нервную систему"
        })

    if m.get("hippuric") == "high" or m.get("mandelic") == "high":
        out.append({
            "id": "external_load",
            "label": "Внешняя метаболическая нагрузка",
            "meaning": "возможное влияние питания/химии/среды"
        })

    if "устал" in symptoms or "слаб" in symptoms:
        out.append({
            "id": "fatigue_pattern",
            "label": "Паттерн усталости",
            "meaning": "состояние требует системной коррекции"
        })

    return out
