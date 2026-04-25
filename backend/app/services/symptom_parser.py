from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ParsedSymptoms:
    primary_symptom: str | None = None
    triggers: list[str] = field(default_factory=list)
    duration: str | None = None
    severity: str | None = None
    body_system: str | None = None
    normalized_symptoms: list[str] = field(default_factory=list)
    red_flag_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _contains_any(text: str, variants: list[str]) -> bool:
    return any(variant in text for variant in variants)


def parse_symptoms(text: str) -> ParsedSymptoms:
    """
    Мягкий rule-based парсер симптомов.
    Ничего не диагностирует, а только выделяет сигналы для дальнейшего слоя логики.
    """
    t = (text or "").strip().lower()
    if not t:
        return ParsedSymptoms()

    primary_symptom: str | None = None
    triggers: list[str] = []
    normalized_symptoms: list[str] = []
    red_flag_signals: list[str] = []
    duration: str | None = None
    severity: str | None = None
    body_system: str | None = None

    symptom_rules = [
        ("fever", ["температур", "лихорад", "жар", "озноб"]),
        ("cough", ["каш", "покашлив"]),
        ("sore_throat", ["горло болит", "боль в горле", "першит горло"]),
        ("runny_nose", ["насморк", "течет из носа", "заложен нос"]),
        ("headache", ["головная боль", "болит голова", "мигрень"]),
        ("abdominal_pain", ["боль в животе", "живот болит", "болит желудок", "болит справа в животе"]),
        ("nausea", ["тошнит", "тошнота", "подташнивает"]),
        ("vomiting", ["рвота", "вырвало", "рвёт"]),
        ("diarrhea", ["диарея", "понос", "жидкий стул"]),
        ("constipation", ["запор", "нет стула"]),
        ("weakness", ["слабость", "упадок сил"]),
        ("dizziness", ["головокруж", "кружится голова"]),
        ("chest_pain", ["боль в груди", "жжение в груди", "давит в груди"]),
        ("shortness_of_breath", ["одышка", "трудно дышать", "не хватает воздуха"]),
        ("palpitations", ["сердцебиение", "тахикард", "пульс высокий"]),
        ("rash", ["сыпь", "высыпания", "пятна на коже"]),
        ("itching", ["зуд", "чешется"]),
        ("back_pain", ["боль в спине", "болит спина", "поясница болит"]),
        ("joint_pain", ["болят суставы", "сустав болит"]),
        ("urinary_pain", ["больно мочиться", "жжение при мочеиспускании"]),
    ]

    for normalized_name, variants in symptom_rules:
        if _contains_any(t, variants):
            normalized_symptoms.append(normalized_name)

    if normalized_symptoms:
        primary_symptom = normalized_symptoms[0]

    trigger_rules = [
        ("fried_food", ["жарен", "жирн"]),
        ("spicy_food", ["острая пища", "острое", "перчёное", "перченое"]),
        ("dairy", ["молоко", "молоч", "сыр", "кефир"]),
        ("alcohol", ["алкоголь", "вино", "пиво", "водка"]),
        ("sunflower_seeds", ["семеч", "семечки"]),
        ("cold_exposure", ["замерз", "переохлад", "продуло"]),
        ("exercise", ["после тренировки", "после нагрузки", "после бега"]),
        ("stress", ["стресс", "нервы", "перенервничал", "переживал"]),
    ]

    for trigger_name, variants in trigger_rules:
        if _contains_any(t, variants):
            triggers.append(trigger_name)

    if _contains_any(t, ["сегодня", "с утра", "несколько часов", "пару часов", "внезапно"]):
        duration = "acute"
    elif _contains_any(t, ["несколько дней", "2 дня", "3 дня", "четвертый день", "неделю"]):
        duration = "days"
    elif _contains_any(t, ["месяц", "месяцами", "давно", "несколько недель", "хроническ"]):
        duration = "chronic_or_subacute"

    if _contains_any(t, ["сильная боль", "очень сильная", "невыносимая", "резкая боль"]):
        severity = "severe"
    elif _contains_any(t, ["умеренная", "средняя", "заметная боль"]):
        severity = "moderate"
    elif normalized_symptoms:
        severity = "mild_or_unspecified"

    gastrointestinal = {"abdominal_pain", "nausea", "vomiting", "diarrhea", "constipation"}
    respiratory = {"cough", "sore_throat", "runny_nose", "shortness_of_breath", "fever"}
    cardiovascular = {"chest_pain", "palpitations", "dizziness"}
    dermatology = {"rash", "itching"}
    musculoskeletal = {"back_pain", "joint_pain"}
    genitourinary = {"urinary_pain"}

    ns = set(normalized_symptoms)
    if ns & gastrointestinal:
        body_system = "gastrointestinal"
    elif ns & respiratory:
        body_system = "respiratory"
    elif ns & cardiovascular:
        body_system = "cardiovascular"
    elif ns & dermatology:
        body_system = "dermatology"
    elif ns & musculoskeletal:
        body_system = "musculoskeletal"
    elif ns & genitourinary:
        body_system = "genitourinary"

    red_flag_rules = [
        ("chest_pain", ["боль в груди", "давит в груди"]),
        ("shortness_of_breath", ["не хватает воздуха", "трудно дышать", "одышка"]),
        ("blood_in_vomit", ["кровь в рвоте", "рвота с кровью"]),
        ("blood_in_stool", ["кровь в стуле", "черный стул", "чёрный стул"]),
        ("high_fever", ["температура 39", "температура 40", "высокая температура"]),
        ("syncope", ["потерял сознание", "обморок"]),
        ("neurologic_deficit", ["онемела рука", "перекосило лицо", "не могу говорить"]),
    ]

    for flag_name, variants in red_flag_rules:
        if _contains_any(t, variants):
            red_flag_signals.append(flag_name)

    return ParsedSymptoms(
        primary_symptom=primary_symptom,
        triggers=triggers,
        duration=duration,
        severity=severity,
        body_system=body_system,
        normalized_symptoms=normalized_symptoms,
        red_flag_signals=red_flag_signals,
    )


def symptom_context_from_text(text: str) -> dict[str, Any]:
    """
    Удобный хелпер, если в основном коде нужен сразу dict.
    """
    parsed = parse_symptoms(text)
    return parsed.to_dict()