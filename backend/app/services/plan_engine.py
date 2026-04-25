"""Построение плана действий по гипотезам."""


def build_plan(payload, hypotheses):
    plan = {
        "priority_1": [],
        "priority_2": [],
        "tests": []
    }

    ids = [h["id"] for h in hypotheses]

    if "external_load" in ids:
        plan["priority_1"].append("Снизить бытовую химию и ультрапереработанные продукты")

    if "energy_issue" in ids:
        plan["priority_1"].append("Регулярное питание без пропусков")
        plan["priority_2"].append("Оценить калорийность и жиры")

    if "vitamin_deficit" in ids:
        plan["tests"] += ["B12", "Фолат", "Гомоцистеин"]

    if "oxidative_stress" in ids:
        plan["priority_2"].append("Снизить нагрузку и обсудить антиоксидантную поддержку")

    return plan
