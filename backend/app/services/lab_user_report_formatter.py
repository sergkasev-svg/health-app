from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LabMarker:
    code: str
    title: str
    value: Optional[float]
    ref_low: Optional[float]
    ref_high: Optional[float]
    unit: str = ""
    flag: str = "normal"


@dataclass
class UserReportBlock:
    kind: str
    title: str
    items: List[str] = field(default_factory=list)


@dataclass
class UserLabReport:
    severity: str
    headline: str
    blocks: List[UserReportBlock] = field(default_factory=list)
    hidden_debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "headline": self.headline,
            "blocks": [asdict(block) for block in self.blocks],
            "hidden_debug": self.hidden_debug,
        }


LOW_WORDS = ("low", "below", "ниже", "низ", "понижен")
HIGH_WORDS = ("high", "above", "выше", "повыш", "высок")

HARDBLOCK_DIAGNOSES = {
    "малярия",
    "сепсис",
    "covid-19",
    "covid",
    "импетиго",
    "острый отит",
    "анальная трещина",
    "липидный профиль",
    "нарушения сна",
    "инсомния",
}

ALLOWED_LAB_TOPICS = {
    "iron_deficiency",
    "anemia_pattern",
    "possible_allergy",
    "infection_pattern",
    "inflammation_pattern",
    "thyroid_hypo",
    "thyroid_hyper",
}


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _detect_flag(
    value: Optional[float],
    low: Optional[float],
    high: Optional[float],
    raw_flag: Optional[str] = None,
) -> str:
    if raw_flag:
        raw = str(raw_flag).lower()
        if any(word in raw for word in LOW_WORDS):
            return "low"
        if any(word in raw for word in HIGH_WORDS):
            return "high"
    if value is None:
        return "normal"
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    return "normal"


def normalize_lab_rows(rows: List[Dict[str, Any]]) -> List[LabMarker]:
    result: List[LabMarker] = []
    for row in rows or []:
        code = str(row.get("code") or row.get("name") or row.get("title") or "").strip()
        title = str(row.get("title") or row.get("name") or code).strip()
        value = _to_float(row.get("value"))
        ref_low = _to_float(row.get("ref_low") or row.get("norm_low") or row.get("low"))
        ref_high = _to_float(row.get("ref_high") or row.get("norm_high") or row.get("high"))
        unit = str(row.get("unit") or "").strip()
        raw_flag = row.get("flag") or row.get("deviation") or row.get("status")
        flag = _detect_flag(value, ref_low, ref_high, raw_flag)

        result.append(
            LabMarker(
                code=code.lower(),
                title=title,
                value=value,
                ref_low=ref_low,
                ref_high=ref_high,
                unit=unit,
                flag=flag,
            )
        )
    return result


def _find_marker(markers: List[LabMarker], aliases: List[str]) -> Optional[LabMarker]:
    aliases = [a.lower() for a in aliases]
    for marker in markers:
        hay = f"{marker.code} {marker.title}".lower()
        if any(alias in hay for alias in aliases):
            return marker
    return None


def sanitize_doctor_hypotheses_for_user(
    hypotheses: List[Dict[str, Any]] | List[str],
    symptoms: Optional[List[str]] = None,
) -> List[str]:
    symptoms_text = " ".join(str(x).lower() for x in (symptoms or []))
    cleaned: List[str] = []

    for item in hypotheses or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("title") or "").strip()
            prob = float(item.get("probability") or item.get("score") or 0)
        else:
            name = str(item).strip()
            prob = 0.0

        if not name:
            continue

        low_name = name.lower()

        if low_name in HARDBLOCK_DIAGNOSES:
            continue

        if prob and prob < 0.30:
            continue

        if any(x in low_name for x in ["маляр", "сепсис", "covid", "инсомни", "липид", "импетиго", "отит"]):
            continue

        severe_words = ("менингит", "инсульт", "инфаркт", "онколог")
        if any(x in low_name for x in severe_words) and not symptoms_text:
            continue

        cleaned.append(name)

    return list(dict.fromkeys(cleaned))[:3]


def _build_topics(markers: List[LabMarker], context: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    meta: Dict[str, Any] = {"supports": []}
    topics: List[str] = []

    hb = _find_marker(markers, ["гемоглобин", "hemoglobin"])
    mch = _find_marker(markers, ["среднее содержание гемоглобина", "mch"])
    retic_abs = _find_marker(markers, ["абсолютное количество ретикулоцитов", "reticulocyte"])
    eos_pct = _find_marker(markers, ["относительное количество эозинофилов", "eosinophil", "эозинофил"])
    wbc = _find_marker(markers, ["лейкоцит", "wbc"])
    neut = _find_marker(markers, ["нейтрофил", "neutrophil"])
    tsh = _find_marker(markers, ["tsh", "тиреотропный", "тиротропин"])
    free_t4 = _find_marker(markers, ["free t4", "свободный т4", "ft4", "св. т4"])
    free_t3 = _find_marker(markers, ["free t3", "свободный т3", "ft3", "св. т3"])

    # Thyroid rules (primary): TSH first-line
    if tsh and tsh.value is not None:
        if tsh.flag == "high":
            topics.append("thyroid_hypo")
            meta["supports"].append("tsh_high")
        elif tsh.flag == "low":
            topics.append("thyroid_hyper")
            meta["supports"].append("tsh_low")

    iron_score = 0
    if hb and hb.value is not None and hb.ref_low is not None and hb.value <= hb.ref_low + 8:
        iron_score += 1
        meta["supports"].append("hemoglobin_low_borderline")
    if mch and mch.flag == "low":
        iron_score += 2
        meta["supports"].append("mch_low")
    if retic_abs and retic_abs.flag == "low":
        iron_score += 1
        meta["supports"].append("reticulocyte_low")

    if iron_score >= 2:
        topics.extend(["iron_deficiency", "anemia_pattern"])

    if eos_pct and eos_pct.flag == "high":
        topics.append("possible_allergy")
        meta["supports"].append("eosinophils_high")

    symptoms_text = " ".join(str(x).lower() for x in context.get("symptoms", []))
    infection_score = 0
    if wbc and wbc.flag == "high":
        infection_score += 2
    if neut and neut.flag == "high":
        infection_score += 1
    if any(x in symptoms_text for x in ["температура", "лихорадка", "озноб"]):
        infection_score += 1

    if infection_score >= 3:
        topics.append("infection_pattern")
    elif infection_score == 2:
        topics.append("inflammation_pattern")

    topics = [t for t in topics if t in ALLOWED_LAB_TOPICS]
    topics = list(dict.fromkeys(topics))
    return topics[:3], meta


def _has_red_flags(context: Dict[str, Any]) -> bool:
    symptoms_text = " ".join(str(x).lower() for x in context.get("symptoms", []))
    red_flags = (
        "боль в груди",
        "одышка в покое",
        "обморок",
        "потеря сознания",
        "сильная слабость",
        "черный стул",
        "кровь в стуле",
    )
    return any(flag in symptoms_text for flag in red_flags)


def _severity(topics: List[str], context: Dict[str, Any]) -> str:
    if _has_red_flags(context):
        return "urgent"
    if "infection_pattern" in topics:
        return "moderate"
    if topics:
        return "mild"
    return "normal"


def _headline(topics: List[str], severity: str) -> str:
    if severity == "urgent":
        return "Есть симптомы, при которых лучше срочно обратиться за медицинской помощью."
    if "thyroid_hypo" in topics:
        return "По анализу щитовидной железы: возможен гипотиреоз. Рекомендуется консультация врача и контроль свободного T4."
    if "thyroid_hyper" in topics:
        return "По анализу щитовидной железы: возможна гиперфункция. Рекомендуется консультация врача и контроль свободного T4/T3."
    if "iron_deficiency" in topics and "possible_allergy" in topics:
        return "Есть лёгкие изменения: возможен дефицит железа и признаки аллергии."
    if "iron_deficiency" in topics:
        return "Есть лёгкие изменения, которые могут говорить о дефиците железа."
    if "possible_allergy" in topics:
        return "Есть лёгкие изменения, похожие на аллергическую реакцию."
    if "infection_pattern" in topics:
        return "Есть признаки, которые могут говорить о воспалении или инфекции."
    return "По анализу нет явных серьёзных отклонений, но самочувствие всё равно важно учитывать."


def _meaning_items(topics: List[str]) -> List[str]:
    items: List[str] = []
    if "thyroid_hypo" in topics:
        items.append("Повышенный TSH может указывать на сниженную функцию щитовидной железы. Для уточнения нужен свободный T4 и осмотр врача.")
    if "thyroid_hyper" in topics:
        items.append("Пониженный TSH может указывать на избыток гормонов щитовидной железы. Для уточнения нужны свободный T4, при необходимости T3 и осмотр врача.")
    if "iron_deficiency" in topics or "anemia_pattern" in topics:
        items.append("Показатели крови могут соответствовать раннему дефициту железа.")
        items.append("Это иногда проявляется слабостью, утомляемостью и головокружением.")
    if "possible_allergy" in topics:
        items.append("Небольшое повышение эозинофилов бывает при аллергии или другой реакции организма.")
    if "infection_pattern" in topics or "inflammation_pattern" in topics:
        items.append("Есть признаки, которые стоит обсудить с врачом в контексте воспаления или инфекции.")
    return items[:5]


def _question_items(topics: List[str]) -> List[str]:
    items: List[str] = []
    if "thyroid_hypo" in topics:
        items.append("Есть ли усталость, зябкость, сухость кожи, набор веса?")
    if "thyroid_hyper" in topics:
        items.append("Есть ли сердцебиение, потливость, снижение веса, нервозность?")
    if "iron_deficiency" in topics or "anemia_pattern" in topics:
        items.append("Есть ли слабость или быстрая утомляемость?")
        items.append("Бывает ли головокружение или одышка при нагрузке?")
    if "possible_allergy" in topics:
        items.append("Есть ли аллергия, зуд, сыпь, насморк или контакт с аллергенами?")
    if "infection_pattern" in topics:
        items.append("Есть ли температура, озноб или другие признаки инфекции?")
    return items[:5]


def _tests_items(topics: List[str]) -> List[str]:
    items: List[str] = []
    if "thyroid_hypo" in topics or "thyroid_hyper" in topics:
        items.extend(["Свободный T4", "При необходимости свободный T3", "Антитела к ТПО и к ТГ по назначению врача"])
    if "iron_deficiency" in topics or "anemia_pattern" in topics:
        items.extend(["Ферритин", "Сывороточное железо", "ОЖСС или трансферрин"])
    if "possible_allergy" in topics and len(items) < 5:
        items.append("Обсудить с врачом поиск причины аллергии по симптомам")
    if "infection_pattern" in topics and len(items) < 5:
        items.append("СРБ")
    return items[:5]


def _self_care_items(topics: List[str]) -> List[str]:
    items: List[str] = []
    if "thyroid_hypo" in topics or "thyroid_hyper" in topics:
        items.append("Не начинать приём препаратов щитовидной железы без назначения врача. Записаться на приём для интерпретации анализов.")
    if "iron_deficiency" in topics or "anemia_pattern" in topics:
        items.append("Добавить в питание продукты с железом: мясо, печень, бобовые, гречка.")
        items.append("Не запивать основную еду чаем или кофе.")
    if "possible_allergy" in topics and len(items) < 5:
        items.append("Вспомнить, не было ли новых продуктов, лекарств, бытовой химии или контакта с аллергенами.")
    if "infection_pattern" in topics and len(items) < 5:
        items.append("Следить за температурой и самочувствием, при ухудшении обратиться к врачу.")
    return items[:5]


def _urgent_items(topics: List[str]) -> List[str]:
    items = [
        "сильная слабость или резкое ухудшение состояния",
        "одышка в покое",
        "обморок или предобморочное состояние",
    ]
    if "infection_pattern" in topics:
        items.append("высокая температура, которая не снижается")
    return items[:4]


def _compute_secondary_indices(markers: List[LabMarker]) -> Dict[str, Any]:
    """NLR, SII, SIRI, AISI — только для слоя врача/отладки; не использовать как самостоятельный диагноз."""
    neut = _find_marker(markers, ["нейтрофил", "neutrophil"])
    lymph = _find_marker(markers, ["лимфоцит", "lymphocyte"])
    mono = _find_marker(markers, ["моноцит", "monocyte"])
    plat = _find_marker(markers, ["тромбоцит", "platelet", "plt"])
    out: Dict[str, Any] = {}
    n = (neut and neut.value) or None
    l_ = (lymph and lymph.value) or None
    if n is not None and l_ is not None and l_ > 0:
        out["NLR"] = round(n / l_, 2)
    if "NLR" in out and plat and plat.value is not None:
        out["SII"] = round(plat.value * out["NLR"], 0)
    if "NLR" in out and mono and mono.value is not None:
        out["SIRI"] = round(mono.value * out["NLR"], 2)
    if "SIRI" in out and plat and plat.value is not None:
        out["AISI"] = round(plat.value * out["SIRI"], 0)
    return out


def build_user_lab_report(
    lab_rows: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
) -> UserLabReport:
    context = context or {}
    markers = normalize_lab_rows(lab_rows)
    topics, meta = _build_topics(markers, context)
    severity = _severity(topics, context)
    headline = _headline(topics, severity)

    blocks: List[UserReportBlock] = [
        UserReportBlock(kind="summary", title="Коротко", items=[headline]),
    ]

    meaning = _meaning_items(topics)
    if meaning:
        blocks.append(UserReportBlock(kind="meaning", title="Что это может значить", items=meaning))

    questions = _question_items(topics)
    if questions:
        blocks.append(UserReportBlock(kind="questions", title="Что стоит уточнить", items=questions))

    tests = _tests_items(topics)
    if tests:
        blocks.append(UserReportBlock(kind="tests", title="Что можно проверить", items=tests))

    self_care = _self_care_items(topics)
    if self_care:
        blocks.append(UserReportBlock(kind="self_care", title="Что можно сделать сейчас", items=self_care))

    blocks.append(UserReportBlock(kind="urgent", title="Когда срочно к врачу", items=_urgent_items(topics)))

    hidden_debug: Dict[str, Any] = {
        "topics": topics,
        "supports": meta.get("supports", []),
        "marker_count": len(markers),
    }
    # Secondary indices (NLR, SII, SIRI, AISI) — только при отсутствии явного диагноза или низкой уверенности
    if not topics or (context.get("confidence") is not None and float(context.get("confidence", 1)) < 0.6):
        secondary = _compute_secondary_indices(markers)
        if secondary:
            hidden_debug["secondary_indices"] = secondary
            hidden_debug["secondary_note"] = "supportive_only_not_diagnostic"

    return UserLabReport(
        severity=severity,
        headline=headline,
        blocks=blocks,
        hidden_debug=hidden_debug,
    )


def render_user_lab_report_text(report: UserLabReport) -> str:
    lines: List[str] = []
    for block in report.blocks:
        lines.append(block.title)
        for item in block.items:
            lines.append(f"• {item}")
        lines.append("")
    return "\n".join(lines).strip()
