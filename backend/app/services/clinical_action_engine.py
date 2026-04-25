"""
Паттерн → смысл → что делать → что проверить → важно.
Обогащение ответа по отчёту органических кислот без назначений от имени врача.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _uniq_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_pattern_summary(markers: Dict[str, Any]) -> List[str]:
    patterns: List[str] = []
    if markers.get("external_metabolic_load"):
        patterns.append(
            "Есть признаки внешней метаболической нагрузки: часть отклонений может быть связана с питанием, бытовой химией, лекарствами или БАДами."
        )
    if markers.get("oxidative_stress_glutathione"):
        patterns.append(
            "Есть признаки повышенной окислительной нагрузки и напряжения глутатионового обмена."
        )
    if markers.get("energy_fat_oxidation_shift"):
        patterns.append(
            "Есть признаки снижения эффективности энергетического обмена и β-окисления жирных кислот."
        )
    if markers.get("b9_b12_cofactor_risk"):
        patterns.append(
            "Есть признаки возможного дефицита витаминно-коферментной поддержки, особенно по оси фолат/B12."
        )
    if markers.get("immune_tryptophan_shift"):
        patterns.append(
            "Есть признаки иммунно-воспалительного или триптофанового сдвига, который нужно оценивать только вместе с симптомами."
        )
    return patterns


def build_what_it_means(markers: Dict[str, Any]) -> List[str]:
    meaning: List[str] = []
    if markers.get("oxidative_stress_glutathione"):
        meaning.append(
            "Организм может работать в режиме перегрузки: антиоксидантная защита ослаблена, поэтому хуже переносится метаболический стресс."
        )
    if markers.get("energy_fat_oxidation_shift"):
        meaning.append(
            "Это может проявляться утомляемостью, слабостью, нестабильной переносимостью интервалов между едой и более медленным восстановлением."
        )
    if markers.get("b9_b12_cofactor_risk"):
        meaning.append(
            "Если подтвердится недостаток фолата/B12, это может влиять на энергию, нервную систему, кроветворение и общее самочувствие."
        )
    if markers.get("external_metabolic_load"):
        meaning.append(
            "Даже хорошая нутритивная поддержка будет работать слабее, если не уменьшить внешнюю нагрузку."
        )
    return meaning


def build_actions(
    markers: Dict[str, Any], age_years: int | None = None
) -> Dict[str, List[str]]:
    actions = {
        "priority_now": [],
        "nutrition": [],
        "supportive_options": [],
        "tests_to_confirm": [],
        "doctor_red_flags": [],
    }
    if markers.get("external_metabolic_load"):
        actions["priority_now"] += [
            "На 2–4 недели максимально сократить бытовую химию с запахами, ароматизаторы, освежители воздуха и контакт с растворителями.",
            "Уменьшить ультрапереработанную еду, напитки с красителями, избыток ароматизаторов и продукты из нагреваемого пластика.",
            "На очной консультации отдельно разобрать лекарства, БАДы и бытовые экспозиции.",
        ]
    if markers.get("energy_fat_oxidation_shift"):
        actions["priority_now"] += [
            "Избегать длительных голодных интервалов, пока не понятен вклад энергообмена; питание сделать регулярным.",
            "Следить за достаточным белком и нормальным общим калоражем без крайностей.",
        ]
        actions["nutrition"] += [
            "Стабильный режим питания без пропусков приёмов пищи.",
            "Достаточное количество белка по возрасту и массе тела; точную норму лучше согласовать с врачом/педиатром.",
            "Обычные цельные жиры в рационе, без акцента на трансжиры и избыток жареного.",
        ]
        actions["supportive_options"] += [
            "Обсудить с врачом/педиатром поддержку энергетического обмена: магний, коэнзим Q10, L-карнитин — только если это уместно по возрасту и контексту."
        ]
    if markers.get("oxidative_stress_glutathione"):
        actions["priority_now"] += [
            "Снизить общий метаболический стресс: режим сна, уменьшение химической нагрузки, аккуратный рацион без перегруза добавками."
        ]
        actions["nutrition"] += [
            "Поддерживать обычный рацион с продуктами, содержащими белок и серосодержащие аминокислоты.",
            "Добавить овощи и фрукты как источник пищевых антиоксидантов, без попытки лечиться мегадозами.",
        ]
        actions["supportive_options"] += [
            "Любую нутритивную поддержку по оси глутатиона обсуждать с врачом; самостоятельно не назначать высокие дозы добавок ребёнку."
        ]
    if markers.get("b9_b12_cofactor_risk"):
        actions["priority_now"] += ["Подтвердить статус фолата/B12 до начала активной коррекции."]
        actions["tests_to_confirm"] += [
            "Витамин B12",
            "Фолиевая кислота (B9)",
            "Гомоцистеин",
        ]
        actions["nutrition"] += [
            "Проверить, достаточно ли в рационе источников фолата и B12 с учётом возраста и особенностей питания."
        ]
        actions["supportive_options"] += [
            "Если дефицит подтвердится, схему коррекции должен выбрать врач; особенно у ребёнка 10 лет."
        ]
    if markers.get("immune_tryptophan_shift"):
        actions["tests_to_confirm"] += [
            "Оценка клинического контекста воспаления по назначению врача."
        ]
    actions["nutrition"] += [
        "Постепенно увеличивать пищевые волокна по переносимости.",
        "Сделать рацион более предсказуемым: меньше хаотичных сладостей и ультрапереработанных продуктов.",
    ]
    actions["doctor_red_flags"] += [
        "Срочно очно к врачу при выраженной слабости, потере веса, повторной рвоте, обезвоживании, ухудшении состояния или новых неврологических симптомах."
    ]
    for k, v in actions.items():
        actions[k] = _uniq_keep_order(v)
    return actions


def render_patient_facing_plan(
    markers: Dict[str, Any], age_years: int | None = None
) -> str:
    pattern_block = build_pattern_summary(markers)
    meaning_block = build_what_it_means(markers)
    actions = build_actions(markers, age_years=age_years)
    lines: List[str] = []
    lines.append("Что видно по паттерну")
    for item in pattern_block[:4]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Что это может значить")
    for item in meaning_block[:4]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Что делать сначала")
    for item in actions["priority_now"][:5]:
        lines.append(f"- {item}")
    if actions["nutrition"]:
        lines.append("")
        lines.append("Питание и базовая поддержка")
        for item in actions["nutrition"][:5]:
            lines.append(f"- {item}")
    if actions["supportive_options"]:
        lines.append("")
        lines.append("Что можно обсудить с врачом")
        for item in actions["supportive_options"][:5]:
            lines.append(f"- {item}")
    if actions["tests_to_confirm"]:
        lines.append("")
        lines.append("Что проверить дальше")
        for item in actions["tests_to_confirm"][:6]:
            lines.append(f"- {item}")
    lines.append("")
    lines.append("Важно")
    for item in actions["doctor_red_flags"][:2]:
        lines.append(f"- {item}")
    lines.append(
        "- Это не диагноз. Такие результаты нужно сопоставлять с жалобами, рационом, лекарствами и очной оценкой врача."
    )
    return "\n".join(lines)


def derive_markers_from_physician_report(report: Dict[str, Any]) -> Dict[str, bool]:
    """
    Строит словарь маркеров для clinical_action_engine из physician report (organic acids).
    Использует clinical_scores.ranked_domains и имена маркеров из abnormal_markers_table / grouped_interpretation_table.
    """
    markers: Dict[str, bool] = {
        "external_metabolic_load": False,
        "oxidative_stress_glutathione": False,
        "energy_fat_oxidation_shift": False,
        "b9_b12_cofactor_risk": False,
        "immune_tryptophan_shift": False,
    }

    def _norm(s: str) -> str:
        return (s or "").strip().lower().replace("ё", "е")

    ranked = report.get("clinical_scores") or {}
    domain_keys = [
        str(d.get("key") or "") for d in (ranked.get("ranked_domains") or [])[:6]
    ]
    if "xenobiotics" in domain_keys:
        markers["external_metabolic_load"] = True
    if "glutathione" in domain_keys:
        markers["oxidative_stress_glutathione"] = True
    if "energy" in domain_keys or "beta_oxidation" in domain_keys:
        markers["energy_fat_oxidation_shift"] = True
    if "cofactors" in domain_keys:
        markers["b9_b12_cofactor_risk"] = True

    abnormal = report.get("abnormal_markers_table") or []
    groups = report.get("grouped_interpretation_table") or []
    all_names: List[str] = []
    for row in abnormal:
        name = _norm(str(row.get("name") or ""))
        if name:
            all_names.append(name)
    for g in groups:
        for m in g.get("markers") or []:
            all_names.append(_norm(str(m)))

    for n in all_names:
        if "метилгиппур" in n or "гиппур" in n or "миндальн" in n:
            markers["external_metabolic_load"] = True
        if "пироглутам" in n:
            markers["oxidative_stress_glutathione"] = True
        if "малонов" in n or "себацин" in n:
            markers["energy_fat_oxidation_shift"] = True
        if "формиминоглутам" in n or "figlu" in n:
            markers["b9_b12_cofactor_risk"] = True
        if "пиколинов" in n:
            markers["immune_tryptophan_shift"] = True

    return markers


def build_organic_acids_blocks_from_clinical_actions(
    report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Строит блоки для user_report_structured по паттерну → смысл → что делать → что проверить → важно.
    Если маркеров нет, возвращает пустой список (caller может использовать обычные блоки).
    """
    markers = derive_markers_from_physician_report(report)
    if not any(markers.values()):
        return []

    doc_summary = report.get("document_summary") or {}
    try:
        age_years = int(doc_summary.get("age_years") or 0)
    except (TypeError, ValueError):
        age_years = 0

    pattern_block = build_pattern_summary(markers)
    meaning_block = build_what_it_means(markers)
    actions = build_actions(markers, age_years=age_years)

    blocks: List[Dict[str, Any]] = [
        {
            "title": "Что видно по паттерну",
            "items": pattern_block[:4]
            or ["По анализу выявлены изменения, требующие клинической оценки."],
        },
        {
            "title": "Что это может значить простыми словами",
            "items": meaning_block[:4]
            or ["Интерпретация возможна только вместе с жалобами и очной оценкой врача."],
        },
        {
            "title": "Что делать сначала",
            "items": actions["priority_now"][:5] or ["Показать результат врачу."],
        },
    ]

    if actions["nutrition"]:
        blocks.append(
            {
                "title": "Питание и базовая поддержка",
                "items": actions["nutrition"][:5],
            }
        )
    if actions["supportive_options"]:
        blocks.append(
            {
                "title": "Что можно обсудить с врачом",
                "items": actions["supportive_options"][:5],
            }
        )
    if actions["tests_to_confirm"]:
        blocks.append(
            {
                "title": "Что проверить дальше",
                "items": actions["tests_to_confirm"][:6],
            }
        )

    blocks.append(
        {
            "title": "Важно понимать",
            "items": actions["doctor_red_flags"][:2]
            + [
                "Это не диагноз. Результаты нужно сопоставлять с жалобами, рационом, лекарствами и очной оценкой врача."
            ],
        }
    )
    return blocks
