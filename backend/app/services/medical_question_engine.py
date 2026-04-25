"""
MedicalQuestionEngine: генерация только необходимых уточняющих вопросов
(жалобы, питание, активность). Останавливается, когда данных достаточно для анализа.
Изолированный модуль.
"""
from typing import Any

from app.services.voice_medical_input import extract_symptoms_nutrition_activity_intent


def _has_fever_or_allergy_context(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in ["температура", "лихорадка", "жар", "аллерг", "аллергия"])


def suggest_clarifying_questions(
    user_message: str,
    chat_history: list,
    has_lab_data: bool = False,
    max_questions: int = 3,
) -> list[str]:
    """
    Возвращает список из 1–3 уточняющих вопросов в зависимости от намерения и уже собранных данных.
    При первичном запросе: жалобы, начало симптомов, температура, аллергии.
    По питанию: частота приёма пищи, дефицит железа/D/белка, вода.
    По активности: шаги, регулярность тренировок, тип (кардио, силовые, растяжка).
    Останавливает вопросы, когда информации достаточно (или has_lab_data и описание есть).
    """
    extracted = extract_symptoms_nutrition_activity_intent(user_message or "")
    intent = extracted.get("intent") or "general"
    symptoms = extracted.get("symptoms") or []
    nutrition = extracted.get("nutrition_mentions") or []
    activity = extracted.get("activity_mentions") or []

    # Уже есть развёрнутое описание и/или анализы — не задаём лишних вопросов
    msg_len = len((user_message or "").strip())
    if has_lab_data and msg_len > 100:
        return []
    if msg_len > 300 and (symptoms or nutrition or activity):
        return []

    questions: list[str] = []
    lower_msg = (user_message or "").lower()
    is_skin_case = any(k in lower_msg for k in ["пятн", "сып", "зуд", "чеш", "кож", "красн", "кольц"])

    # Триаж «плохо после еды / семечки / жирная пища» — задаём блоки вопросов для гастро-симптома без острой боли
    is_food_discomfort = (
        any(k in lower_msg for k in ["семечк", "подсолнечник", "плохо после", "после еды", "жирн", "поел", "поела", "съел", "съела"])
        and any(k in lower_msg for k in ["тошнот", "плохое самочувствие", "ухудшилось", "недомога", "тяжесть"])
        and "острая боль" not in lower_msg and "кинжальн" not in lower_msg
    )
    if intent == "illness" and is_food_discomfort:
        if "когда" not in lower_msg and "появил" not in lower_msg:
            questions.append("Когда появились симптомы после еды (сразу, через час)?")
        if "рвот" not in lower_msg and "рвота" not in lower_msg:
            questions.append("Есть ли рвота или сильная боль в животе?")
        if "температур" not in lower_msg:
            questions.append("Есть ли температура, слабость или головокружение?")
        if "тяжесть" not in lower_msg and "подреберь" not in lower_msg:
            questions.append("Есть ли тяжесть в правом подреберье, вздутие, изжога или горечь во рту?")
        if "сколько" not in lower_msg and ("съел" in lower_msg or "съела" in lower_msg or "семеч" in lower_msg):
            questions.append("Сколько примерно семечек или жирной пищи съели? Бывали ли такие симптомы раньше?")
        if len(questions) < max_questions:
            questions.append("Есть ли заболевания желудка или желчного пузыря? Бывает ли тошнота после жирной пищи?")
        return questions[:max_questions]

    if intent == "illness":
        if is_skin_case:
            questions.append("Где именно расположено пятно и какого оно размера (примерно в см)? Одно оно или их несколько?")
            questions.append("Есть ли шелушение, мокнутие, боль, повышение температуры кожи или гной?")
            questions.append("Был ли контакт с новыми средствами/животными, укусами, спортзалом или бассейном за последние 1–2 недели?")
            return questions[:max_questions]
        if not _has_fever_or_allergy_context(user_message or ""):
            if "начал" not in (user_message or "").lower() and "давно" not in (user_message or "").lower():
                questions.append("Как давно появились симптомы? Что предшествовало их появлению?")
        if "температур" not in (user_message or "").lower() and "температура" not in (user_message or "").lower():
            questions.append("Есть ли температура? Если да — какая?")
        if "аллерг" not in (user_message or "").lower():
            questions.append("Есть ли известные аллергии или непереносимость лекарств?")
        if not questions:
            questions.append("Что уже пробовали облегчить состояние? Принимали ли какие-то препараты?")
    elif intent == "nutrition":
        questions.append("Как часто вы едите в течение дня? Есть ли ощущение дефицита железа, витамина D или белка?")
        questions.append("Сколько примерно воды или жидкости выпиваете в день?")
        if len(questions) < max_questions:
            questions.append("Есть ли ограничения в питании (аллергии, вегетарианство, заболевания ЖКТ)?")
    elif intent == "fitness":
        questions.append("Сколько в среднем шагов в день или как часто тренируетесь?")
        questions.append("Какой тип нагрузки преобладает: кардио, силовые, растяжка, йога?")
        if len(questions) < max_questions:
            questions.append("Было ли в последнее время переутомление или боль после тренировок?")
    else:
        if msg_len < 80:
            questions.append("Что беспокоит, как давно и что уже пробовали?")

    return questions[:max_questions]
