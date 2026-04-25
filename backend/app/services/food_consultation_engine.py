from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# TEXT HELPERS
# ============================================================
def normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = text.replace("ё", "е")
    bad = [",", ".", "!", "?", ":", ";", "(", ")", "[", "]", "{", "}", '"', "'"]
    for ch in bad:
        text = text.replace(ch, " ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def contains_any(text: str, phrases: list[str]) -> list[str]:
    matched: list[str] = []
    for phrase in phrases:
        if phrase in text:
            matched.append(phrase)
    return list(dict.fromkeys(matched))


# ============================================================
# DATA MODELS
# ============================================================
@dataclass
class FoodRoutingContext:
    recurrent: bool = False
    debug: bool = False
    ask_followups: bool = True
    doctor_safe: bool = True


@dataclass
class TriggerEvent:
    text: str
    trigger_groups: list[str]
    ranked_causes: list[str]
    zone: str
    cluster: str


@dataclass
class TriggerMemoryState:
    events: list[TriggerEvent] = field(default_factory=list)

    def add_event(
        self,
        *,
        text: str,
        trigger_groups: list[str],
        ranked_causes: list[str],
        zone: str,
        cluster: str,
    ) -> None:
        self.events.append(
            TriggerEvent(
                text=text,
                trigger_groups=trigger_groups,
                ranked_causes=ranked_causes,
                zone=zone,
                cluster=cluster,
            )
        )

    def repeated_trigger_groups(self, min_count: int = 2) -> list[str]:
        counts: dict[str, int] = {}
        for event in self.events:
            for group in event.trigger_groups:
                counts[group] = counts.get(group, 0) + 1
        return sorted([key for key, value in counts.items() if value >= min_count])

    def repeated_causes(self, min_count: int = 2) -> list[str]:
        counts: dict[str, int] = {}
        for event in self.events:
            for cause in event.ranked_causes:
                counts[cause] = counts.get(cause, 0) + 1
        return sorted([key for key, value in counts.items() if value >= min_count])

    def summary(self) -> dict[str, Any]:
        return {
            "events_count": len(self.events),
            "repeated_trigger_groups": self.repeated_trigger_groups(),
            "repeated_causes": self.repeated_causes(),
        }


# ============================================================
# RULES / VOCAB
# ============================================================
TRIGGER_GROUPS: dict[str, list[str]] = {
    "fatty_fried": [
        "жирное",
        "жареное",
        "жареной",
        "жирной",
        "семечки",
        "орехи",
        "фастфуд",
        "картошка фри",
        "картофель фри",
        "шашлык",
        "маслянистое",
        "майонез",
        "бургеры",
        "бургер",
        "чипсы",
    ],
    "dairy": [
        "молоко",
        "мороженое",
        "сливки",
        "творог",
        "йогурт",
        "кефир",
        "сырок",
        "сметана",
        "молочный",
    ],
    "histamine_like": [
        "вино",
        "сыр",
        "копчености",
        "копчёности",
        "колбаса",
        "колбасы",
        "ферментированное",
        "выдержанный",
        "выдержанные",
        "квашеное",
        "шампанское",
    ],
    "sweet_load": [
        "сладкое",
        "торт",
        "десерт",
        "пирожное",
        "шоколад",
        "сладкий напиток",
        "газировка",
        "сок",
        "мед",
        "мёд",
        "конфеты",
        "печенье",
    ],
    "fodmap_like": [
        "лук",
        "чеснок",
        "бобовые",
        "фасоль",
        "горох",
        "яблоки",
        "груши",
        "арбуз",
        "сок",
        "мед",
        "мёд",
        "сахарозаменитель",
        "сорбит",
        "ксилит",
    ],
    "alcohol": [
        "алкоголь",
        "вино",
        "пиво",
        "водка",
        "коньяк",
        "шампанское",
    ],
}

ZONE_RULES: dict[str, list[str]] = {
    "right_upper_abdominal_zone": [
        "справа под ребром",
        "справа под ребрами",
        "справа под рёбрами",
        "правое подреберье",
        "горечь во рту",
        "тянет справа",
    ],
    "upper_gi_zone": [
        "верх живота",
        "эпигастр",
        "под ложечкой",
        "изжога",
        "жжение",
        "кислая отрыжка",
        "отрыжка",
        "тошнота",
        "тяжесть",
        "переполненность",
        "раннее насыщение",
    ],
    "bowel_zone": [
        "вздутие",
        "урчание",
        "газы",
        "понос",
        "диарея",
        "жидкий стул",
        "послабление",
        "крутит живот",
        "бурлит",
    ],
    "systemic_zone": [
        "слабость",
        "головная боль",
        "сонливость",
        "дурнота",
        "головокружение",
        "потливость",
        "дрожь",
        "подташнивает",
    ],
}

RED_FLAGS = [
    "сильная боль",
    "нарастающая боль",
    "боль в груди",
    "одышка",
    "обморок",
    "кровь в рвоте",
    "кровь в стуле",
    "черный стул",
    "чёрный стул",
    "желтуха",
    "температура",
    "неукротимая рвота",
    "не могу пить",
    "невозможно пить",
    "теряю сознание",
    "спутанность",
]

CAUSES: dict[str, dict[str, Any]] = {
    "functional_dyspepsia": {
        "title": "Диспепсия / раздражение верхнего ЖКТ",
        "zone": "upper_gi_zone",
        "symptoms": ["тяжесть", "переполненность", "тошнота", "отрыжка", "верх живота", "под ложечкой"],
    },
    "fatty_food_overload": {
        "title": "Перегрузка жирной или жареной пищей",
        "zone": "upper_gi_zone",
        "symptoms": ["жирное", "жареное", "тяжесть", "тошнота", "переполненность"],
    },
    "reflux_pattern": {
        "title": "Рефлюкс / изжога после еды",
        "zone": "upper_gi_zone",
        "symptoms": ["изжога", "жжение", "кислая отрыжка", "хуже лежа", "хуже лёжа"],
    },
    "biliary_pattern": {
        "title": "Желчный паттерн",
        "zone": "right_upper_abdominal_zone",
        "symptoms": ["справа под ребром", "справа под ребрами", "справа под рёбрами", "горечь", "жирное"],
    },
    "pancreatic_warning_if_severe": {
        "title": "Панкреатический настораживающий паттерн",
        "zone": "upper_gi_zone",
        "symptoms": ["боль в спину", "многократная рвота", "температура", "сильная боль"],
    },
    "dairy_lactose_pattern": {
        "title": "Лактозный / молочный паттерн",
        "zone": "bowel_zone",
        "symptoms": ["молоко", "мороженое", "творог", "вздутие", "урчание", "понос", "жидкий стул"],
    },
    "fodmap_fermentation_pattern": {
        "title": "FODMAP / брожение углеводов",
        "zone": "bowel_zone",
        "symptoms": ["лук", "чеснок", "бобовые", "вздутие", "газы", "урчание", "понос"],
    },
    "ibs_pattern_if_recurrent": {
        "title": "IBS-паттерн при повторяемости",
        "zone": "bowel_zone",
        "symptoms": ["вздутие", "изменение стула", "повторяется", "часто"],
    },
    "infectious_pattern_if_acute": {
        "title": "Острый инфекционный кишечный паттерн",
        "zone": "bowel_zone",
        "symptoms": ["рвота", "понос", "температура", "подозрительная еда"],
    },
    "postprandial_vascular_pattern": {
        "title": "Сосудистая / вегетативная реакция после еды",
        "zone": "systemic_zone",
        "symptoms": ["слабость", "сонливость", "головокружение", "дурнота", "ватное состояние"],
    },
    "sugar_glucose_pattern": {
        "title": "Реакция на сладкое / глюкозный паттерн",
        "zone": "systemic_zone",
        "symptoms": ["сладкое", "дрожь", "потливость", "головокружение", "слабость"],
    },
    "fatty_food_systemic_overload": {
        "title": "Системная реакция на жирную пищу",
        "zone": "systemic_zone",
        "symptoms": ["жирное", "жареное", "тошнота", "головная боль", "слабость"],
    },
    "histamine_conditional_pattern": {
        "title": "Гистаминовый паттерн",
        "zone": "systemic_zone",
        "symptoms": ["вино", "сыр", "копчености", "копчёности", "покраснение", "сердце колотится", "сердцебиение"],
    },
    "alcohol_related_pattern": {
        "title": "Алкогольная / смешанная реакция",
        "zone": "systemic_zone",
        "symptoms": ["алкоголь", "вино", "пиво", "тошнота", "головная боль"],
    },
    "dehydration_pattern": {
        "title": "Легкое обезвоживание",
        "zone": "systemic_zone",
        "symptoms": ["сухость", "мало пил", "головная боль", "слабость"],
    },
    "simple_overeating": {
        "title": "Переедание",
        "zone": "upper_gi_zone",
        "symptoms": ["переел", "много съел", "объелся", "переполненность", "тяжесть"],
    },
    "simple_overeating_or_fast_eating": {
        "title": "Переедание / быстрый прием пищи",
        "zone": "bowel_zone",
        "symptoms": ["быстро ел", "на ходу", "переел", "вздутие", "отрыжка"],
    },
    "ulcer_or_gastritis_risk_pattern": {
        "title": "Гастрит / язвенный риск-паттерн",
        "zone": "upper_gi_zone",
        "symptoms": ["жжение", "болит натощак", "ночью болит", "нпвп", "алкоголь"],
    },
    "carbohydrate_malabsorption_pattern": {
        "title": "Непереносимость части углеводов",
        "zone": "bowel_zone",
        "symptoms": ["сок", "мед", "мёд", "фрукты", "вздутие", "понос"],
    },
    "urgent_general_route": {
        "title": "Срочная общая ветка",
        "zone": "urgent_route",
        "symptoms": RED_FLAGS,
    },
}

CLUSTER_TO_TEMPLATE = {
    "upper_abdominal_heaviness_after_food": "upper_gi_mild",
    "upper_abdominal_pain_with_nausea": "upper_gi_mild",
    "right_upper_abdominal_discomfort_after_fatty_food": "biliary_like",
    "heartburn_burning_regurgitation_after_food": "reflux_like",
    "bloating_gas_diarrhea_after_dairy": "dairy_like",
    "bloating_gas_after_fodmap": "bloating_bowel_like",
    "acute_diarrhea_plus_vomiting_plus_fever": "infectious_like",
    "nausea_weakness_headache_after_fatty_food": "systemic_after_food",
    "sleepiness_weakness_after_heavy_meal": "systemic_after_food",
    "nausea_headache_after_wine_cheese_smoked_food": "systemic_after_food",
}

TEMPLATES = {
    "base_response": {
        "most_likely": "Похоже, это связано с реакцией на еду или её объём.",
        "alternatives": [
            "возможна реакция верхнего ЖКТ",
            "возможен пищевой триггер",
        ],
        "actions": [
            "пить воду маленькими глотками",
            "не перегружать ЖКТ",
        ],
        "urgent": [
            "если становится хуже",
            "если появляется сильная боль, рвота, температура, кровь",
        ],
    },
    "upper_gi_mild": {
        "most_likely": "Чаще всего это похоже на диспепсию или перегрузку верхнего ЖКТ после тяжёлой еды.",
        "alternatives": [
            "рефлюкс, если есть жжение или кислый привкус",
            "желчный паттерн, если тянет справа под рёбрами после жирного",
            "простое переедание",
        ],
        "actions": [
            "пить воду маленькими глотками",
            "не ложиться сразу после еды",
            "избегать жирной еды несколько часов",
        ],
        "urgent": [
            "сильная или нарастающая боль",
            "многократная рвота",
            "температура",
            "кровь в рвоте или чёрный стул",
        ],
    },
    "biliary_like": {
        "most_likely": "Это похоже на желчный паттерн: жирная пища может провоцировать тошноту, горечь и дискомфорт справа под рёбрами.",
        "alternatives": [
            "перегрузка жирной пищей",
            "верхнебрюшная диспепсия",
        ],
        "actions": [
            "не есть жирное",
            "пить воду небольшими порциями",
            "наблюдать, не усиливается ли боль справа",
        ],
        "urgent": [
            "сильная боль справа под рёбрами",
            "рвота",
            "температура",
            "желтуха",
        ],
    },
    "reflux_like": {
        "most_likely": "Это похоже на рефлюкс или усиление изжоги после еды.",
        "alternatives": [
            "диспепсия",
            "переедание",
        ],
        "actions": [
            "не ложиться",
            "не есть поздно",
            "избегать переедания",
        ],
        "urgent": [
            "боль в груди",
            "затруднение глотания",
            "кровь в рвоте",
            "чёрный стул",
        ],
    },
    "dairy_like": {
        "most_likely": "Это похоже на реакцию на молочный продукт — чаще по типу лактозной непереносимости или чувствительности к продукту.",
        "alternatives": [
            "брожение углеводов",
            "повторяющийся кишечный паттерн",
        ],
        "actions": [
            "временно упростить питание",
            "пить жидкость",
            "отметить связь именно с молочным",
        ],
        "urgent": [
            "кровь в стуле",
            "высокая температура",
            "сильная боль",
            "обезвоживание",
        ],
    },
    "bloating_bowel_like": {
        "most_likely": "Чаще всего это похоже на брожение углеводов, реакцию на конкретный продукт или переедание.",
        "alternatives": [
            "FODMAP-паттерн",
            "молочный паттерн",
            "IBS-подобная чувствительность, если это повторяется",
        ],
        "actions": [
            "пить жидкость",
            "облегчить рацион",
            "отметить продукты-триггеры",
        ],
        "urgent": [
            "кровь в стуле",
            "чёрный стул",
            "высокая температура",
            "сильная боль",
        ],
    },
    "systemic_after_food": {
        "most_likely": "Чаще всего это похоже на смешанную реакцию после еды: нагрузка на ЖКТ плюс сосудистая или вегетативная реакция.",
        "alternatives": [
            "реакция на жирную еду",
            "реакция на сладкое",
            "обезвоживание",
            "реже — алкогольный или гистаминоподобный паттерн",
        ],
        "actions": [
            "сесть или прилечь с приподнятой головой",
            "пить воду",
            "не есть тяжёлую еду дальше",
        ],
        "urgent": [
            "обморок",
            "сильная слабость",
            "боль в груди",
            "одышка",
        ],
    },
    "infectious_like": {
        "most_likely": "Если есть рвота, понос и температура, это уже больше похоже на кишечную инфекцию или острый гастроэнтерит.",
        "alternatives": [
            "реакция на подозрительную еду",
        ],
        "actions": [
            "следить за жидкостью",
            "не допускать обезвоживания",
            "наблюдать за температурой",
        ],
        "urgent": [
            "кровь в стуле",
            "неукротимая рвота",
            "обморок",
            "редкое мочеиспускание",
        ],
    },
}


# ============================================================
# ENGINE
# ============================================================
class FoodConsultationEngine:
    """
    Unified integrated engine for food-related complaints.

    Output:
    {
      "patient_view": {...},
      "doctor_view": {...},
      "machine_view": {...}
    }
    """

    def __init__(self, runtime_patch_config: dict[str, Any] | None = None) -> None:
        self.causes = CAUSES
        self.templates = TEMPLATES
        self.runtime_patch_config = self._normalize_runtime_patch_config(runtime_patch_config)

    # ---------------------------
    # PUBLIC
    # ---------------------------
    def consult(
        self,
        user_text: str,
        *,
        context: FoodRoutingContext | None = None,
        memory_state: TriggerMemoryState | None = None,
        food_journal_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        context = context or FoodRoutingContext()
        memory_state = memory_state or TriggerMemoryState()
        food_journal_entries = food_journal_entries or []

        normalized = normalize_text(user_text)

        severity = self._severity(normalized)
        timeline = self._timeline(normalized)
        matched_red_flags = contains_any(normalized, RED_FLAGS)

        if matched_red_flags:
            care_level = self._care_level(
                matched_red_flags,
                ["urgent_general_route"],
                "high",
                context.recurrent,
                normalized_text=normalized,
            )
            patient_text = self._build_urgent_patient_text(matched_red_flags, care_level["action_hint"])
            result = self._serialize(
                normalized=normalized,
                zone="urgent_route",
                cluster="urgent_route",
                trigger_groups=[],
                ranked_causes=["urgent_general_route"],
                cause_scores={"urgent_general_route": 100},
                evidence_by_cause={"urgent_general_route": ["matched urgent red flags"]},
                confidence={"score": 95, "level": "high", "reasons": ["urgent red flags detected"]},
                care_level=care_level,
                recommendations={
                    "do_now": ["не затягивать с очной оценкой"],
                    "avoid_now": ["самолечение при ухудшении"],
                    "tests_if_recurrent": [],
                    "followup_advice": ["срочная очная оценка"],
                },
                followup_questions=[],
                severity=severity,
                timeline=timeline,
                memory_summary=memory_state.summary(),
                journal_summary=self._analyze_journal(food_journal_entries),
                lab_bridge={
                    "suggested_lab_modules": [],
                    "suggested_tests": [],
                    "rationale": ["приоритет — срочная очная оценка"],
                },
                patient_text=patient_text,
            )
            result["memory_state"] = memory_state
            return result

        trigger_groups, matched_trigger_phrases = self._extract_triggers(normalized)
        zone_scores = self._score_zones(normalized, trigger_groups)
        zone = self._pick_best(zone_scores, fallback="upper_gi_zone")
        cluster_scores = self._score_clusters(normalized, zone, trigger_groups, context.recurrent)
        cluster = self._pick_best(cluster_scores, fallback=self._default_cluster_for_zone(zone))

        cause_scores, evidence_by_cause = self._score_causes(
            normalized=normalized,
            zone=zone,
            cluster=cluster,
            trigger_groups=trigger_groups,
            recurrent=context.recurrent,
        )
        ranked_causes = list(cause_scores.keys())[:5]

        confidence = self._confidence(
            trigger_groups=trigger_groups,
            zone_scores=zone_scores,
            cluster_scores=cluster_scores,
            cause_scores=cause_scores,
            evidence_by_cause=evidence_by_cause,
            repeated_trigger_groups=memory_state.repeated_trigger_groups(),
            repeated_causes=memory_state.repeated_causes(),
        )

        followup_questions: list[str] = []
        if context.ask_followups:
            followup_questions = self._followups(
                zone=zone,
                ranked_causes=ranked_causes,
                confidence_level=confidence["level"],
                recurrent=context.recurrent,
            )

        recommended_tests = self._select_tests(ranked_causes, context.recurrent)
        care_level = self._care_level(
            [],
            ranked_causes,
            confidence["level"],
            context.recurrent,
            normalized_text=normalized,
        )
        recommendations = self._recommendations(ranked_causes, care_level["level"], context.recurrent, recommended_tests)

        memory_state.add_event(
            text=normalized,
            trigger_groups=trigger_groups,
            ranked_causes=ranked_causes,
            zone=zone,
            cluster=cluster,
        )

        journal_summary = self._analyze_journal(food_journal_entries)
        lab_bridge = self._lab_bridge(ranked_causes, context.recurrent, care_level["level"])
        patient_text = self._build_patient_text(
            cluster=cluster,
            ranked_causes=ranked_causes,
            care_level=care_level,
            recommendations=recommendations,
            followup_questions=followup_questions,
            confidence_level=confidence["level"],
            memory_summary=memory_state.summary(),
        )

        result = self._serialize(
            normalized=normalized,
            zone=zone,
            cluster=cluster,
            trigger_groups=trigger_groups,
            ranked_causes=ranked_causes,
            cause_scores=cause_scores,
            evidence_by_cause=evidence_by_cause,
            confidence=confidence,
            care_level=care_level,
            recommendations=recommendations,
            followup_questions=followup_questions,
            severity=severity,
            timeline=timeline,
            memory_summary=memory_state.summary(),
            journal_summary=journal_summary,
            lab_bridge=lab_bridge,
            patient_text=patient_text,
        )
        result["memory_state"] = memory_state

        if context.debug:
            result["machine_view"]["debug"] = {
                "matched_trigger_phrases": matched_trigger_phrases,
                "zone_scores": zone_scores,
                "cluster_scores": cluster_scores,
            }

        return result

    # ---------------------------
    # SEVERITY / TIMELINE
    # ---------------------------
    def _severity(self, normalized: str) -> dict[str, Any]:
        score = 0
        reasons: list[str] = []

        severe_markers = [
            "сильная боль",
            "нестерпимая боль",
            "очень плохо",
            "не могу встать",
            "не могу пить",
            "многократная рвота",
            "обморок",
            "теряю сознание",
        ]
        moderate_markers = [
            "сильная слабость",
            "сильно тошнит",
            "сильно кружится голова",
            "выраженная слабость",
            "ухудшается",
        ]
        mild_markers = [
            "слегка тошнит",
            "немного тошнит",
            "подташнивает",
            "дискомфорт",
            "тяжесть",
        ]

        for marker in severe_markers:
            if marker in normalized:
                score += 25
                reasons.append(f"severe marker: {marker}")
        for marker in moderate_markers:
            if marker in normalized:
                score += 12
                reasons.append(f"moderate marker: {marker}")
        for marker in mild_markers:
            if marker in normalized:
                score += 5
                reasons.append(f"mild marker: {marker}")

        score = max(0, min(score, 100))
        level = "mild"
        if score >= 60:
            level = "severe"
        elif score >= 30:
            level = "moderate"

        return {"score": score, "level": level, "reasons": reasons}

    def _timeline(self, normalized: str) -> dict[str, Any]:
        onset = "unknown"
        duration = "unknown"
        clues: list[str] = []

        if any(x in normalized for x in ["сразу после еды", "сразу после", "через 5 минут", "через 10 минут"]):
            onset = "immediate"
            clues.append("immediate onset")
        elif any(x in normalized for x in ["через полчаса", "через 30 минут", "через час", "после еды"]):
            onset = "early_postprandial"
            clues.append("early postprandial onset")
        elif any(x in normalized for x in ["через несколько часов", "через 2 часа", "через 3 часа", "к вечеру", "ночью"]):
            onset = "delayed"
            clues.append("delayed onset")

        if any(x in normalized for x in ["весь день", "не проходит", "уже второй день", "уже 2 дня", "уже 3 дня", "постоянно"]):
            duration = "persistent"
            clues.append("persistent duration")

        return {
            "onset_timing": onset,
            "duration_hint": duration,
            "timeline_clues": clues,
        }

    # ---------------------------
    # EXTRACTORS
    # ---------------------------
    def _extract_triggers(self, normalized: str) -> tuple[list[str], dict[str, list[str]]]:
        groups: list[str] = []
        matched_phrases: dict[str, list[str]] = {}
        for group, words in TRIGGER_GROUPS.items():
            matched = contains_any(normalized, words)
            if matched:
                groups.append(group)
                matched_phrases[group] = matched
        return groups, matched_phrases

    def _score_zones(self, normalized: str, trigger_groups: list[str]) -> dict[str, int]:
        scores: dict[str, int] = {}
        for zone, symptoms in ZONE_RULES.items():
            matched = contains_any(normalized, symptoms)
            scores[zone] = sum(self._symptom_weight(x) for x in matched)
            self._apply_zone_runtime_patch(scores, normalized, zone, trigger_groups)
        return scores

    def _score_clusters(
        self,
        normalized: str,
        zone: str,
        trigger_groups: list[str],
        recurrent: bool,
    ) -> dict[str, int]:
        scores: dict[str, int] = {}

        if zone == "right_upper_abdominal_zone":
            scores["right_upper_abdominal_discomfort_after_fatty_food"] = 10
            if "fatty_fried" in trigger_groups:
                scores["right_upper_abdominal_discomfort_after_fatty_food"] += 6

        if zone == "upper_gi_zone":
            scores["upper_abdominal_heaviness_after_food"] = 8
            if any(x in normalized for x in ["боль", "болит", "тошнота"]):
                scores["upper_abdominal_pain_with_nausea"] = 9
            if any(x in normalized for x in ["изжога", "жжение", "кислая отрыжка", "хуже лежа", "хуже лёжа"]):
                scores["heartburn_burning_regurgitation_after_food"] = 14

        if zone == "bowel_zone":
            scores["bloating_gas_after_fodmap"] = 8
            if "dairy" in trigger_groups:
                scores["bloating_gas_diarrhea_after_dairy"] = 14
            if all(x in normalized for x in ["рвота", "понос"]) or all(x in normalized for x in ["диарея", "температура"]):
                scores["acute_diarrhea_plus_vomiting_plus_fever"] = 18

        if zone == "systemic_zone":
            scores["sleepiness_weakness_after_heavy_meal"] = 8
            if "fatty_fried" in trigger_groups:
                scores["nausea_weakness_headache_after_fatty_food"] = 14
            if "histamine_like" in trigger_groups:
                scores["nausea_headache_after_wine_cheese_smoked_food"] = 14

        if recurrent and zone == "bowel_zone":
            scores["recurrent_bowel_like"] = scores.get("recurrent_bowel_like", 0) + 4

        return scores

    def _default_cluster_for_zone(self, zone: str) -> str:
        mapping = {
            "right_upper_abdominal_zone": "right_upper_abdominal_discomfort_after_fatty_food",
            "upper_gi_zone": "upper_abdominal_heaviness_after_food",
            "bowel_zone": "bloating_gas_after_fodmap",
            "systemic_zone": "sleepiness_weakness_after_heavy_meal",
        }
        return mapping.get(zone, "upper_abdominal_heaviness_after_food")

    # ---------------------------
    # EVIDENCE / SCORING
    # ---------------------------
    def _score_causes(
        self,
        *,
        normalized: str,
        zone: str,
        cluster: str,
        trigger_groups: list[str],
        recurrent: bool,
    ) -> tuple[dict[str, int], dict[str, list[str]]]:
        cause_scores: dict[str, int] = {}
        evidence: dict[str, list[str]] = {}

        cluster_defaults = self._cluster_default_causes(cluster, zone)
        for idx, cause_id in enumerate(cluster_defaults):
            score = max(12 - idx * 2, 2)
            cause_scores[cause_id] = cause_scores.get(cause_id, 0) + score
            evidence.setdefault(cause_id, []).append(f"base cluster ranking: {cluster}")

        for cause_id in list(cause_scores.keys()):
            meta = self.causes.get(cause_id, {})
            matched = contains_any(normalized, meta.get("symptoms", []))
            if matched:
                cause_scores[cause_id] += len(matched) * 2
                evidence.setdefault(cause_id, []).append(f"matched symptoms: {', '.join(matched)}")

        # trigger compatibility
        for cause_id in list(cause_scores.keys()):
            title = self.causes[cause_id]["title"].lower()

            if "молоч" in title and "dairy" in trigger_groups:
                cause_scores[cause_id] += 5
                evidence.setdefault(cause_id, []).append("trigger compatibility: dairy")

            if "гистамин" in title and "histamine_like" in trigger_groups:
                cause_scores[cause_id] += 6
                evidence.setdefault(cause_id, []).append("trigger compatibility: histamine_like")

            if "глюкоз" in title and "sweet_load" in trigger_groups:
                cause_scores[cause_id] += 6
                evidence.setdefault(cause_id, []).append("trigger compatibility: sweet_load")

            if "желч" in title and "fatty_fried" in trigger_groups:
                cause_scores[cause_id] += 5
                evidence.setdefault(cause_id, []).append("trigger compatibility: fatty_fried")

            if "алкоголь" in title and "alcohol" in trigger_groups:
                cause_scores[cause_id] += 4
                evidence.setdefault(cause_id, []).append("trigger compatibility: alcohol")

        # cluster specific promotions
        if cluster == "heartburn_burning_regurgitation_after_food":
            cause_scores["reflux_pattern"] = cause_scores.get("reflux_pattern", 0) + 10
            evidence.setdefault("reflux_pattern", []).append("cluster promotion: reflux-like")

        if cluster == "bloating_gas_diarrhea_after_dairy":
            cause_scores["dairy_lactose_pattern"] = cause_scores.get("dairy_lactose_pattern", 0) + 10
            evidence.setdefault("dairy_lactose_pattern", []).append("cluster promotion: dairy bowel pattern")

        if cluster == "nausea_headache_after_wine_cheese_smoked_food":
            cause_scores["histamine_conditional_pattern"] = cause_scores.get("histamine_conditional_pattern", 0) + 8
            evidence.setdefault("histamine_conditional_pattern", []).append("cluster promotion: histamine-like")

        # guardrails against overcalling
        if not recurrent:
            cause_scores.pop("ibs_pattern_if_recurrent", None)
            evidence.pop("ibs_pattern_if_recurrent", None)

        if "histamine_like" not in trigger_groups:
            cause_scores.pop("histamine_conditional_pattern", None)
            evidence.pop("histamine_conditional_pattern", None)

        if not any(x in normalized for x in ["боль в спину", "многократная рвота", "температура", "сильная боль"]):
            cause_scores.pop("pancreatic_warning_if_severe", None)
            evidence.pop("pancreatic_warning_if_severe", None)

        self._apply_cause_runtime_patch(
            cause_scores=cause_scores,
            evidence=evidence,
            normalized=normalized,
            zone=zone,
            trigger_groups=trigger_groups,
            recurrent=recurrent,
        )

        ranked = dict(sorted(cause_scores.items(), key=lambda x: x[1], reverse=True))
        return ranked, evidence

    def _cluster_default_causes(self, cluster: str, zone: str) -> list[str]:
        mapping = {
            "right_upper_abdominal_discomfort_after_fatty_food": [
                "biliary_pattern",
                "fatty_food_overload",
                "pancreatic_warning_if_severe",
            ],
            "upper_abdominal_heaviness_after_food": [
                "functional_dyspepsia",
                "fatty_food_overload",
                "simple_overeating",
                "reflux_pattern",
            ],
            "upper_abdominal_pain_with_nausea": [
                "functional_dyspepsia",
                "biliary_pattern",
                "ulcer_or_gastritis_risk_pattern",
                "pancreatic_warning_if_severe",
            ],
            "heartburn_burning_regurgitation_after_food": [
                "reflux_pattern",
                "functional_dyspepsia",
            ],
            "bloating_gas_diarrhea_after_dairy": [
                "dairy_lactose_pattern",
                "simple_overeating_or_fast_eating",
            ],
            "bloating_gas_after_fodmap": [
                "fodmap_fermentation_pattern",
                "carbohydrate_malabsorption_pattern",
                "simple_overeating_or_fast_eating",
            ],
            "acute_diarrhea_plus_vomiting_plus_fever": [
                "infectious_pattern_if_acute",
                "urgent_general_route",
            ],
            "nausea_weakness_headache_after_fatty_food": [
                "fatty_food_systemic_overload",
                "postprandial_vascular_pattern",
                "fatty_food_overload",
            ],
            "sleepiness_weakness_after_heavy_meal": [
                "postprandial_vascular_pattern",
                "simple_overeating",
                "sugar_glucose_pattern",
                "dehydration_pattern",
            ],
            "nausea_headache_after_wine_cheese_smoked_food": [
                "histamine_conditional_pattern",
                "alcohol_related_pattern",
                "postprandial_vascular_pattern",
            ],
        }
        if cluster in mapping:
            return mapping[cluster]
        fallback = {
            "right_upper_abdominal_zone": ["biliary_pattern", "fatty_food_overload"],
            "upper_gi_zone": ["functional_dyspepsia", "fatty_food_overload", "reflux_pattern"],
            "bowel_zone": ["dairy_lactose_pattern", "fodmap_fermentation_pattern", "simple_overeating_or_fast_eating"],
            "systemic_zone": ["postprandial_vascular_pattern", "fatty_food_systemic_overload", "sugar_glucose_pattern"],
        }
        return fallback.get(zone, ["functional_dyspepsia", "simple_overeating"])

    # ---------------------------
    # CONFIDENCE / FOLLOWUPS / CARE
    # ---------------------------
    def _confidence(
        self,
        *,
        trigger_groups: list[str],
        zone_scores: dict[str, int],
        cluster_scores: dict[str, int],
        cause_scores: dict[str, int],
        evidence_by_cause: dict[str, list[str]],
        repeated_trigger_groups: list[str],
        repeated_causes: list[str],
    ) -> dict[str, Any]:
        score = 0
        reasons: list[str] = []

        if trigger_groups:
            score += min(15, len(trigger_groups) * 5)
            reasons.append(f"trigger groups: {', '.join(trigger_groups)}")

        best_zone = max(zone_scores.values()) if zone_scores else 0
        score += min(15, best_zone)
        reasons.append(f"zone signal: {best_zone}")

        best_cluster = max(cluster_scores.values()) if cluster_scores else 0
        score += min(20, best_cluster)
        reasons.append(f"cluster signal: {best_cluster}")

        if cause_scores:
            vals = list(cause_scores.values())
            top = vals[0]
            gap = top - (vals[1] if len(vals) > 1 else 0)
            score += min(20, top)
            score += min(10, max(gap, 0))
            reasons.append(f"top cause score: {top}")
            reasons.append(f"top gap: {gap}")

        evidence_points = sum(len(v) for v in evidence_by_cause.values())
        score += min(15, evidence_points)
        reasons.append(f"evidence points: {evidence_points}")

        if repeated_trigger_groups:
            score += 5
            reasons.append(f"repeated triggers: {', '.join(repeated_trigger_groups)}")
        if repeated_causes:
            score += 5
            reasons.append(f"repeated causes: {', '.join(repeated_causes)}")

        score = max(0, min(score, 100))
        level = "low"
        if score >= 70:
            level = "high"
        elif score >= 40:
            level = "medium"

        return {"score": score, "level": level, "reasons": reasons}

    def _followups(
        self,
        *,
        zone: str,
        ranked_causes: list[str],
        confidence_level: str,
        recurrent: bool,
    ) -> list[str]:
        _ = ranked_causes
        _ = recurrent
        if confidence_level == "high":
            return []

        if zone == "right_upper_abdominal_zone":
            return [
                "Дискомфорт именно справа под рёбрами или по центру живота?",
                "Есть ли рвота, температура или отдаёт ли боль в спину?",
                "Такое бывает именно после жирной еды?",
            ]

        if zone == "upper_gi_zone":
            return [
                "Это больше тяжесть после еды или именно боль?",
                "Есть ли жжение, кислый привкус или хуже, когда ложитесь?",
                "Было ли переедание или очень тяжёлая еда?",
            ]

        if zone == "bowel_zone":
            return [
                "Это было после молочного, сладкого или продуктов вроде лука, чеснока, бобовых?",
                "Есть только вздутие и урчание или ещё и жидкий стул?",
                "Такое повторяется или это разовый эпизод?",
            ]

        if zone == "systemic_zone":
            return [
                "Это было после жирной еды, сладкого или алкоголя?",
                "Есть ли потливость, дрожь или выраженная сонливость?",
                "Такое бывало раньше после похожей еды?",
            ]

        return []

    def _care_level(
        self,
        matched_red_flags: list[str],
        ranked_causes: list[str],
        confidence_level: str,
        recurrent: bool,
        normalized_text: str = "",
    ) -> dict[str, str]:
        flags = set(matched_red_flags)

        emergency_flags = {
            "боль в груди",
            "одышка",
            "обморок",
            "кровь в рвоте",
            "кровь в стуле",
            "чёрный стул",
            "черный стул",
            "спутанность",
        }
        urgent_flags = {
            "сильная боль",
            "нарастающая боль",
            "температура",
            "неукротимая рвота",
            "желтуха",
            "не могу пить",
            "невозможно пить",
        }
        emergency_patch = (
            self.runtime_patch_config.get("care_level_changes", {})
            .get("emergency_threshold", {})
            .get("increase_emergency_sensitivity", {})
        )
        for marker in emergency_patch.get("force_emergency_on", []):
            emergency_flags.add(normalize_text(str(marker)))

        if flags.intersection(emergency_flags):
            return {
                "level": "emergency",
                "reason": "Есть тревожные признаки высокого риска.",
                "action_hint": "Нужна неотложная помощь без откладывания.",
            }
        urgent_flag_hits = flags.intersection(urgent_flags)
        urgent_patch = self.runtime_patch_config.get("urgent_threshold_changes", {}).get("global", {})
        if self._should_escalate_urgent_from_patch(normalized_text):
            urgent_flag_hits = set(urgent_flags)
        if urgent_flag_hits and self._should_reduce_urgent_by_patch(urgent_flag_hits, urgent_patch):
            urgent_flag_hits = set()

        if urgent_flag_hits:
            return {
                "level": "urgent",
                "reason": "Есть признаки, которые не стоит разбирать как обычную бытовую реакцию.",
                "action_hint": "Нужна срочная очная оценка в ближайшее время.",
            }
        if self._promote_routine_from_patch(recurrent=recurrent, confidence_level=confidence_level):
            return {
                "level": "routine_doctor",
                "reason": "Повторяемость/неопределённость по runtime-патчу требует плановой оценки.",
                "action_hint": "Лучше перейти к плановой очной проверке.",
            }
        if recurrent:
            return {
                "level": "routine_doctor",
                "reason": "Паттерн повторяется.",
                "action_hint": "Нужна плановая очная оценка и разбор причин.",
            }
        if confidence_level == "low":
            return {
                "level": "routine_doctor",
                "reason": "Сигнал недостаточно чёткий для уверенного домашнего объяснения.",
                "action_hint": "Если это не проходит или повторится, нужна плановая оценка.",
            }
        if any(c in ranked_causes for c in ["biliary_pattern", "ulcer_or_gastritis_risk_pattern"]):
            return {
                "level": "routine_doctor",
                "reason": "Есть паттерн, который лучше подтверждать при повторении или сохранении жалоб.",
                "action_hint": "Если жалобы сохраняются или повторяются, нужна плановая проверка.",
            }
        return {
            "level": "home",
            "reason": "Похоже на бытовую постпрандиальную реакцию без красных флагов.",
            "action_hint": "Можно начать с домашнего наблюдения и щадящего режима.",
        }

    # ---------------------------
    # RECOMMENDATIONS / TESTS / LAB BRIDGE
    # ---------------------------
    def _select_tests(self, ranked_causes: list[str], recurrent: bool) -> list[str]:
        if not recurrent:
            return []

        cause_set = set(ranked_causes)
        tests: list[str] = []

        if "biliary_pattern" in cause_set or "fatty_food_overload" in cause_set:
            tests.extend(["АЛТ", "АСТ", "билирубин", "ГГТ", "УЗИ ОБП"])
        if "pancreatic_warning_if_severe" in cause_set:
            tests.extend(["амилаза", "липаза"])
        if "dairy_lactose_pattern" in cause_set:
            tests.extend(["пищевой дневник", "оценка переносимости молочного"])
        if "functional_dyspepsia" in cause_set or "reflux_pattern" in cause_set:
            tests.extend(["оценка H. pylori по показаниям"])
        if "histamine_conditional_pattern" in cause_set:
            tests.extend(["обсуждать только при типичной повторяемости"])

        return list(dict.fromkeys(tests))

    def _recommendations(
        self,
        ranked_causes: list[str],
        care_level: str,
        recurrent: bool,
        recommended_tests: list[str],
    ) -> dict[str, Any]:
        do_now = ["пить воду маленькими порциями", "не перегружать ЖКТ тяжёлой едой"]
        avoid_now: list[str] = []
        followup_advice: list[str] = []

        cause_set = set(ranked_causes)

        if "reflux_pattern" in cause_set:
            do_now.extend(["не ложиться сразу после еды", "есть меньшими порциями"])
            avoid_now.extend(["поздний ужин", "обильную жирную еду"])

        if "fatty_food_overload" in cause_set or "fatty_food_systemic_overload" in cause_set:
            do_now.append("дать организму время восстановиться без жирной еды несколько часов")
            avoid_now.extend(["жирное", "жареное", "переедание"])

        if "biliary_pattern" in cause_set:
            do_now.append("наблюдать, не усиливается ли дискомфорт справа под рёбрами")
            avoid_now.extend(["жирную пищу", "очень тяжёлую еду"])

        if "dairy_lactose_pattern" in cause_set:
            do_now.append("отметить связь симптомов именно с молочным")
            avoid_now.append("молочные продукты до уточнения триггера")

        if "fodmap_fermentation_pattern" in cause_set:
            do_now.append("отметить связь с луком, чесноком, бобовыми, соками")
            avoid_now.extend(["продукты-триггеры", "большие объёмы тяжёлой еды"])

        if "sugar_glucose_pattern" in cause_set:
            do_now.append("наблюдать, нет ли повторяемости именно после сладкого")
            avoid_now.extend(["много сладкого за раз", "сладкое после тяжёлой еды"])

        if care_level == "home":
            followup_advice.append("если симптомы уменьшаются — достаточно наблюдения")
        elif care_level == "routine_doctor":
            followup_advice.append("если это повторяется — стоит перейти к плановой проверке")
        elif care_level in {"urgent", "emergency"}:
            followup_advice.append("не затягивать с очной оценкой")

        if recurrent and recommended_tests:
            followup_advice.append("при повторении можно обсудить базовое обследование")

        return {
            "do_now": list(dict.fromkeys(do_now)),
            "avoid_now": list(dict.fromkeys(avoid_now)),
            "tests_if_recurrent": list(dict.fromkeys(recommended_tests)),
            "followup_advice": list(dict.fromkeys(followup_advice)),
        }

    def _lab_bridge(self, ranked_causes: list[str], recurrent: bool, care_level: str) -> dict[str, Any]:
        modules: list[str] = []
        tests: list[str] = []
        rationale: list[str] = []

        cause_set = set(ranked_causes)

        if "biliary_pattern" in cause_set or "fatty_food_overload" in cause_set:
            modules.append("hepatobiliary_module")
            tests.extend(["АЛТ", "АСТ", "билирубин", "ГГТ", "УЗИ ОБП"])
            rationale.append("жирная пища / желчный паттерн")

        if "pancreatic_warning_if_severe" in cause_set:
            modules.append("pancreatic_module")
            tests.extend(["амилаза", "липаза"])
            rationale.append("панкреатический настораживающий паттерн")

        if "dairy_lactose_pattern" in cause_set:
            modules.append("food_intolerance_module")
            tests.extend(["пищевой дневник", "оценка переносимости молочного"])
            rationale.append("молочный / лактозный паттерн")

        if "reflux_pattern" in cause_set or "functional_dyspepsia" in cause_set:
            modules.append("upper_gi_module")
            tests.extend(["оценка H. pylori по показаниям"])
            rationale.append("верхний ЖКТ / диспепсия / рефлюкс")

        if "histamine_conditional_pattern" in cause_set:
            modules.append("histamine_pattern_module")
            tests.extend(["обсуждать только при типичной повторяемости"])
            rationale.append("гистаминоподобный повторяющийся паттерн")

        if care_level in {"urgent", "emergency"}:
            rationale.append("приоритет — очная оценка, а не амбулаторный скрининг")

        if not recurrent:
            tests = [t for t in tests if t in {"пищевой дневник"}]

        return {
            "suggested_lab_modules": list(dict.fromkeys(modules)),
            "suggested_tests": list(dict.fromkeys(tests)),
            "rationale": list(dict.fromkeys(rationale)),
        }

    # ---------------------------
    # FOOD JOURNAL
    # ---------------------------
    def _analyze_journal(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        food_counts: dict[str, int] = {}
        symptom_counts: dict[str, int] = {}
        pair_counts: dict[tuple[str, str], int] = {}

        for raw in entries:
            foods = [str(x).strip().lower() for x in raw.get("food_items", []) if str(x).strip()]
            syms = [str(x).strip().lower() for x in raw.get("symptoms", []) if str(x).strip()]

            for food in foods:
                food_counts[food] = food_counts.get(food, 0) + 1
            for sym in syms:
                symptom_counts[sym] = symptom_counts.get(sym, 0) + 1
            for food in foods:
                for sym in syms:
                    pair_counts[(food, sym)] = pair_counts.get((food, sym), 0) + 1

        repeated_foods = sorted([k for k, v in food_counts.items() if v >= 2])
        repeated_symptoms = sorted([k for k, v in symptom_counts.items() if v >= 2])

        likely_pairs = [
            {"food": food, "symptom": sym, "count": count}
            for (food, sym), count in sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)
            if count >= 2
        ][:10]

        summary_parts: list[str] = []
        if repeated_foods:
            summary_parts.append("Повторяющиеся продукты: " + ", ".join(repeated_foods))
        if repeated_symptoms:
            summary_parts.append("Повторяющиеся симптомы: " + ", ".join(repeated_symptoms))
        if likely_pairs:
            summary_parts.append("Частые пары: " + "; ".join(f"{x['food']} → {x['symptom']} ({x['count']})" for x in likely_pairs[:5]))

        return {
            "repeated_foods": repeated_foods,
            "repeated_symptoms": repeated_symptoms,
            "likely_trigger_pairs": likely_pairs,
            "summary_text": " | ".join(summary_parts) if summary_parts else "Повторяемых связей пока недостаточно.",
        }

    # ---------------------------
    # BUILD REPORTS
    # ---------------------------
    def _build_patient_text(
        self,
        *,
        cluster: str,
        ranked_causes: list[str],
        care_level: dict[str, str],
        recommendations: dict[str, Any],
        followup_questions: list[str],
        confidence_level: str,
        memory_summary: dict[str, Any],
    ) -> str:
        _ = confidence_level
        template_name = CLUSTER_TO_TEMPLATE.get(cluster, "base_response")
        template = self.templates.get(template_name, self.templates["base_response"])

        lines: list[str] = []
        lines.append(f"Что вероятнее всего:\n- {template['most_likely']}")

        alt_lines = []
        for cause_id in ranked_causes[:4]:
            title = self.causes.get(cause_id, {}).get("title", cause_id)
            alt_lines.append(f"- {title}")
        for alt in template.get("alternatives", []):
            alt_lines.append(f"- {alt}")
        lines.append("Какие ещё причины возможны:\n" + "\n".join(alt_lines[:6]))

        if recommendations.get("do_now"):
            lines.append("Что делать сейчас:\n" + "\n".join(f"- {x}" for x in recommendations["do_now"]))

        if recommendations.get("avoid_now"):
            lines.append("Чего пока лучше избегать:\n" + "\n".join(f"- {x}" for x in recommendations["avoid_now"]))

        lines.append(f"Уровень действий сейчас:\n- {care_level['level']}: {care_level['action_hint']}")

        if recommendations.get("tests_if_recurrent"):
            lines.append("Если это повторяется:\n" + "\n".join(f"- {x}" for x in recommendations["tests_if_recurrent"]))

        if followup_questions:
            lines.append("Чтобы точнее понять ситуацию:\n" + "\n".join(f"- {q}" for q in followup_questions[:3]))

        repeated_triggers = memory_summary.get("repeated_trigger_groups", [])
        if repeated_triggers:
            lines.append("Что уже выглядит повторяющимся:\n" + "\n".join(f"- {x}" for x in repeated_triggers))

        lines.append("Когда лучше не тянуть:\n" + "\n".join(f"- {x}" for x in template.get("urgent", [])))

        return "\n\n".join(lines).strip()

    def _build_urgent_patient_text(self, matched_red_flags: list[str], action_hint: str) -> str:
        return (
            "Похоже, здесь есть признаки, которые лучше не разбирать как обычную пищевую реакцию.\n\n"
            "Что настораживает:\n"
            + "\n".join(f"- {x}" for x in matched_red_flags)
            + f"\n\nЧто делать прямо сейчас:\n- {action_hint}"
        )

    def _serialize(
        self,
        *,
        normalized: str,
        zone: str,
        cluster: str,
        trigger_groups: list[str],
        ranked_causes: list[str],
        cause_scores: dict[str, int],
        evidence_by_cause: dict[str, list[str]],
        confidence: dict[str, Any],
        care_level: dict[str, Any],
        recommendations: dict[str, Any],
        followup_questions: list[str],
        severity: dict[str, Any],
        timeline: dict[str, Any],
        memory_summary: dict[str, Any],
        journal_summary: dict[str, Any],
        lab_bridge: dict[str, Any],
        patient_text: str,
    ) -> dict[str, Any]:
        doctor_view = {
            "normalized_input": normalized,
            "zone": zone,
            "cluster": cluster,
            "trigger_groups": trigger_groups,
            "ranked_causes": ranked_causes,
            "cause_scores": cause_scores,
            "evidence_by_cause": evidence_by_cause,
            "confidence": confidence,
            "care_level": care_level,
            "recommendations": recommendations,
            "followup_questions": followup_questions,
            "memory_summary": memory_summary,
            "severity": severity,
            "timeline": timeline,
            "journal_summary": journal_summary,
            "lab_bridge": lab_bridge,
        }

        machine_view = {
            "normalized_input": normalized,
            "zone": zone,
            "cluster": cluster,
            "trigger_groups": trigger_groups,
            "ranked_causes": ranked_causes,
            "cause_scores": cause_scores,
            "confidence": confidence,
            "care_level": care_level["level"],
            "severity": severity,
            "timeline": timeline,
            "memory_summary": memory_summary,
            "journal_summary": journal_summary,
            "lab_bridge": lab_bridge,
        }

        return {
            "patient_view": {
                "text": patient_text,
                "care_level": care_level["level"],
            },
            "doctor_view": doctor_view,
            "machine_view": machine_view,
        }

    # ---------------------------
    # UTILS
    # ---------------------------
    def _pick_best(self, scores: dict[str, int], fallback: str) -> str:
        if not scores:
            return fallback
        best_key, best_value = max(scores.items(), key=lambda x: x[1])
        if best_value <= 0:
            return fallback
        return best_key

    def _symptom_weight(self, symptom: str) -> int:
        weights = {
            "справа под ребром": 5,
            "справа под ребрами": 5,
            "справа под рёбрами": 5,
            "кислая отрыжка": 5,
            "диарея": 5,
            "рвота": 5,
            "температура": 5,
            "изжога": 5,
            "жжение": 5,
            "вздутие": 4,
            "урчание": 4,
            "газы": 4,
            "слабость": 4,
            "головокружение": 4,
            "головная боль": 4,
            "горечь во рту": 4,
            "тяжесть": 3,
            "тошнота": 3,
            "отрыжка": 3,
            "сонливость": 3,
            "подташнивает": 3,
        }
        return weights.get(symptom, 1)

    # ---------------------------
    # RUNTIME PATCH SUPPORT
    # ---------------------------
    def _normalize_runtime_patch_config(self, runtime_patch_config: dict[str, Any] | None) -> dict[str, Any]:
        base: dict[str, Any] = {
            "zone_weight_boosts": {},
            "cause_score_boosts": {},
            "cause_score_reductions": {},
            "urgent_threshold_changes": {},
            "care_level_changes": {},
            "recurrent_logic_changes": {},
        }
        if not runtime_patch_config:
            return base
        for key, value in runtime_patch_config.items():
            base[key] = deepcopy(value)
        return base

    def _apply_zone_runtime_patch(
        self,
        scores: dict[str, int],
        normalized: str,
        zone: str,
        trigger_groups: list[str],
    ) -> None:
        zone_patch = self.runtime_patch_config.get("zone_weight_boosts", {}).get(zone, {})
        if not isinstance(zone_patch, dict):
            return

        for marker, payload in zone_patch.items():
            if not isinstance(payload, dict):
                continue
            marker_norm = normalize_text(str(marker))
            delta = int(payload.get("delta", 0))
            if delta == 0:
                continue

            marker_hit = False
            if marker_norm.startswith("__trigger__:"):
                trigger_group = marker_norm.split(":", 1)[1].strip()
                marker_hit = trigger_group in trigger_groups
            elif marker_norm and marker_norm in normalized:
                marker_hit = True

            if not marker_hit:
                continue

            scores[zone] = max(0, scores.get(zone, 0) + delta)
            for competitor in payload.get("reduce_competition_from", []):
                competitor_key = str(competitor)
                scores[competitor_key] = max(0, scores.get(competitor_key, 0) - delta)

    def _apply_cause_runtime_patch(
        self,
        *,
        cause_scores: dict[str, int],
        evidence: dict[str, list[str]],
        normalized: str,
        zone: str,
        trigger_groups: list[str],
        recurrent: bool,
    ) -> None:
        boost_patch = self.runtime_patch_config.get("cause_score_boosts", {})
        if isinstance(boost_patch, dict):
            for cause, cause_rules in boost_patch.items():
                if not isinstance(cause_rules, dict):
                    continue
                matches = 0
                total_delta = 0
                needs_combo = False
                for phrase, payload in cause_rules.items():
                    phrase_norm = normalize_text(str(phrase))
                    if not phrase_norm or phrase_norm not in normalized:
                        continue
                    payload_dict = payload if isinstance(payload, dict) else {}
                    delta = int(payload_dict.get("delta", 0))
                    if delta == 0:
                        continue
                    needs_combo = needs_combo or bool(payload_dict.get("require_combination", False))
                    matches += 1
                    total_delta += delta
                    evidence.setdefault(cause, []).append(f"runtime boost: {phrase_norm} (+{delta})")

                if total_delta and (not needs_combo or matches >= 2):
                    cause_scores[cause] = cause_scores.get(cause, 0) + total_delta

        reduction_patch = self.runtime_patch_config.get("cause_score_reductions", {})
        if isinstance(reduction_patch, dict):
            for cause, rules in reduction_patch.items():
                if cause not in cause_scores or not isinstance(rules, dict):
                    continue
                global_rule = rules.get("__global__", {})
                if not isinstance(global_rule, dict):
                    continue
                reduce_when = global_rule.get("reduce_when", [])
                if reduce_when and not self._matches_reduce_when(
                    reduce_when=reduce_when,
                    normalized=normalized,
                    zone=zone,
                    trigger_groups=trigger_groups,
                ):
                    continue
                delta = int(global_rule.get("delta", 0))
                if delta == 0:
                    continue
                cause_scores[cause] = max(0, cause_scores.get(cause, 0) + delta)
                evidence.setdefault(cause, []).append(f"runtime reduction: {delta}")

        recurrent_patch = self.runtime_patch_config.get("recurrent_logic_changes", {})
        if recurrent and isinstance(recurrent_patch, dict):
            for cause, rule in recurrent_patch.items():
                if cause not in cause_scores or not isinstance(rule, dict):
                    continue
                recurrent_bonus = int(rule.get("recurrent_bonus_delta", 0))
                if recurrent_bonus <= 0:
                    continue
                cause_scores[cause] = cause_scores.get(cause, 0) + recurrent_bonus
                evidence.setdefault(cause, []).append(f"runtime recurrent bonus: +{recurrent_bonus}")

    def _matches_reduce_when(
        self,
        *,
        reduce_when: list[Any],
        normalized: str,
        zone: str,
        trigger_groups: list[str],
    ) -> bool:
        text = " ".join(str(x).lower() for x in reduce_when)
        if not text:
            return True

        clues = {
            "gi": zone == "upper_gi_zone" or any(x in normalized for x in ["изжога", "жжение", "отрыжка", "эпигастр"]),
            "reflux": any(x in normalized for x in ["изжога", "жжение", "кислая отрыжка"]),
            "bowel": zone == "bowel_zone" or any(x in normalized for x in ["вздутие", "урчание", "понос", "диарея", "стул"]),
            "ruq": zone == "right_upper_abdominal_zone" or any(x in normalized for x in ["справа под реб", "правое подреберье", "горечь"]),
            "молоч": "dairy" in trigger_groups,
            "glucose": "sweet_load" in trigger_groups,
        }
        needed = [key for key in clues if key in text]
        if not needed:
            return True
        return any(clues[key] for key in needed)

    def _promote_routine_from_patch(self, *, recurrent: bool, confidence_level: str) -> bool:
        routine_patch = (
            self.runtime_patch_config.get("care_level_changes", {})
            .get("routine_doctor_threshold", {})
            .get("lower_threshold_for_recurrent_cases", {})
        )
        if not isinstance(routine_patch, dict):
            return False
        if not routine_patch.get("if_recurrent", False):
            return False
        if not recurrent:
            return False

        conditions = [str(x) for x in routine_patch.get("conditions", [])]
        if not conditions:
            return True

        if "low_or_medium_specificity" in conditions and confidence_level in {"low", "medium"}:
            return True
        if "repeated_pattern" in conditions or "repeated_trigger_group" in conditions:
            return True
        return False

    def _should_reduce_urgent_by_patch(self, urgent_flag_hits: set[str], urgent_patch: dict[str, Any]) -> bool:
        if not isinstance(urgent_patch, dict):
            return False
        if not urgent_patch.get("decrease_urgent_bias", False):
            return False
        if not urgent_patch.get("require_more_specific_red_flags", False):
            return False
        strong_flags = {"желтуха", "неукротимая рвота", "нарастающая боль"}
        return len(urgent_flag_hits) < 2 and not urgent_flag_hits.intersection(strong_flags)

    def _should_escalate_urgent_from_patch(self, normalized_text: str) -> bool:
        urgent_patch = (
            self.runtime_patch_config.get("care_level_changes", {})
            .get("urgent_threshold", {})
            .get("increase_urgent_sensitivity", {})
        )
        if not isinstance(urgent_patch, dict):
            return False
        combos = [str(x) for x in urgent_patch.get("increase_urgent_bias_for", [])]
        normalized = normalize_text(normalized_text)
        for combo in combos:
            parts = [normalize_text(x) for x in combo.split("+") if normalize_text(x)]
            if parts and all(part in normalized for part in parts):
                return True
        return False

