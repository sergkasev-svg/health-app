"""
Проверка красных флагов на стороне сервера (Master Prompt §2).
Если в тексте пользователя или в недавних симптомах есть признаки — сразу RED, без вызова LLM.
"""
import re
from typing import Any, Optional

from app.services.symptom_severity_lookup import build_symptom_severity_context

# Ключевые фразы по docs/MASTER_PROMPT.md (русский + частично английский)
RED_FLAG_RULES = [
    (
        "Выраженная боль в груди",
        r"боль\s+в\s+груди|грудн(ая|ой)\s+боль|chest\s+pain|давит\s+в\s+груди|сжимает\s+груд",
    ),
    (
        "Признаки инсульта или неврологического дефицита",
        r"инсульт|паралич|онемение\s+(лица|руки|ноги)|асимметрия\s+лица|не\s+могу\s+говорить|речь\s+нарушена|stroke|слабость\s+в\s+(руке|ноге)\s+с\s+одной\s+стороны",
    ),
    (
        "Потеря сознания",
        r"потеря\s+сознания|обморок|упал\s+в\s+обморок|потерял\s+сознание|loss\s+of\s+consciousness|syncope",
    ),
    (
        "Сильная боль в животе",
        r"острая\s+боль\s+в\s+животе|сильн(ая|ейшая)\s+боль\s+в\s+животе|нестерпимая\s+боль\s+в\s+животе|severe\s+abdominal",
    ),
    (
        "Одышка или дыхательная недостаточность",
        r"не\s+могу\s+дышать|задыхаюсь|удушье|тяжело\s+дышать|одышка\s+в\s+покое|respiratory\s+distress|удуш",
    ),
    (
        "Высокая стойкая лихорадка у ребёнка",
        r"ребен(ок|ка)\s+температура\s+39|у\s+ребенка\s+(высокая|очень\s+высокая)\s+температура|child\s+fever",
    ),
    (
        "Суицидальные мысли",
        r"суицид|покончить\s+с\s+собой|не\s+хочу\s+жить|мысл[иы]\s+о\s+смерти|suicidal|хочу\s+умереть",
    ),
    (
        "ЖКТ-кровотечение",
        r"кровь\s+в\s+стуле|рвота\s+кровью|чёрный\s+стул|кровавый\s+стул|gi\s+bleeding|мелена|гематемез",
    ),
    (
        "Внезапная очень сильная головная боль",
        r"внезапная\s+сильная\s+головная\s+боль|головная\s+боль\s+как\s+удар|thunderclap|разрыв\s+аневризм",
    ),
]

# Скомпилированные regex для скорости
_COMPILED = [(label, re.compile(pattern, re.IGNORECASE)) for label, pattern in RED_FLAG_RULES]

# Текст ответа при срабатывании красного флага (без вызова LLM)
RED_RESPONSE_TEXT = (
    "Есть признаки, которые могут требовать немедленной медицинской помощи. "
    "Пожалуйста, срочно звоните 103 или в местную службу спасения 112. "
    "Не откладывайте обращение за помощью. "
    "Информация носит справочный характер и не заменяет консультацию врача."
)

EMERGENCY_CALL_PATTERNS = [
    re.compile(r"(вызови|вызвать|вызовите)\s+скор(ую|ая)", re.IGNORECASE),
    re.compile(r"\b(вызови|вызвать)\s+103\b", re.IGNORECASE),
    re.compile(r"\b(позвони|звони)\s+в\s+(скорую|103|112)\b", re.IGNORECASE),
    re.compile(r"\bмне\s+плохо\b", re.IGNORECASE),
    re.compile(r"\bскорая\b", re.IGNORECASE),
    re.compile(r"\b103\b", re.IGNORECASE),
]


_MEDICAL_DISCLAIMER_LINE = (
    "Информация носит справочный характер и не заменяет консультацию врача."
)


def wrap_immediate_emergency_message(medical_body: str, *, profile_address: str = "") -> str:
    """
    Сценарий для явной экстренности: сначала вопрос про вызов скорой, затем медицинский абзац,
    затем подсказка для клиента (таймер ~5 с → тот же сценарий, что у кнопки SOS: дозвон в скорую).
    Фактический звонок и таймер выполняются на стороне клиента/ОС.
    """
    intro = (
        "Похоже на экстренную ситуацию. "
        "Вам сейчас вызвать скорую помощь (103 или единый номер 112)? "
        "Коротко ответьте «да» или «нет».\n\n"
    )
    addr = " ".join(str(profile_address or "").split())
    tail = (
        "Если примерно за 5 секунд ответа нет, можно сразу нажать кнопку SOS в приложении — она выполняет дозвон в скорую; "
        "при безответности клиент может автоматически запустить тот же сценарий, что и SOS (подтвердите на устройстве, если система попросит). "
    )
    if addr:
        tail += f"Если адрес в профиле актуален, продиктуйте его оператору: {addr}. "
    else:
        tail += (
            "Если адрес сейчас назвать сложно, после соединения не кладите трубку: диспетчер сможет уточнить место; "
            "на части сетей возможна привязка вызова к месту — уточните у оператора. "
        )
    tail += _MEDICAL_DISCLAIMER_LINE
    body = (medical_body or "").strip()
    return intro + body + "\n\n" + tail


def ambulance_offer_flow_payload(profile_address: str = "") -> dict[str, Any]:
    """Машиночитаемые подсказки для UI/голоса: тот же обработчик, что у кнопки SOS (дозвон в скорую)."""
    addr = " ".join(str(profile_address or "").split())
    return {
        "ambulance_offer_flow": {
            "enabled": True,
            "ask_user_to_call_ambulance": True,
            "recommended_client_action": "sos_emergency_dial",
            "silence_seconds_before_open_dialer": 5,
            "silence_seconds_before_sos": 5,
            "suggested_dial_uris": ["tel:103", "tel:112"],
            "profile_address_if_any": addr or None,
            "client_note": "Используйте общий с кнопкой SOS сценарий дозвона; по таймауту без ответа — тот же вызов, что по SOS. ОС может запросить подтверждение.",
        }
    }


def is_emergency_call_intent(text: str) -> bool:
    """Явный интент на вызов скорой (голос/текст)."""
    if not text or not text.strip():
        return False
    src = " " + text.strip() + " "
    return any(p.search(src) for p in EMERGENCY_CALL_PATTERNS)


def _contextual_red_response(user_text: str, *, profile_address: str = "") -> str:
    low = (user_text or "").lower()
    detail = ""
    if any(k in low for k in ("сып", "зуд", "крапив", "отек", "отёк")):
        detail = "По описанию есть потенциально опасная аллергическая реакция (сыпь/зуд/отек). "
    elif any(k in low for k in ("голов", "внезап", "самая сильная")):
        detail = "По описанию есть признаки потенциально опасной головной боли. "
    elif any(k in low for k in ("груд", "одыш", "не хватает воздуха")):
        detail = "По описанию есть признаки кардио-респираторного риска. "
    medical_body = detail + "Срочно обратитесь к врачу и звоните 103 или 112 при нарастании симптомов. "
    return wrap_immediate_emergency_message(medical_body, profile_address=profile_address)


def screen_red_flags(text: str) -> list[str]:
    """
    Проверяет текст на наличие красных флагов.
    Возвращает список сработавших красных флагов.
    """
    if not text or not text.strip():
        return []
    combined = " " + text.strip().lower() + " "
    matched: list[str] = []
    for label, pattern in _COMPILED:
        if pattern.search(combined) and label not in matched:
            matched.append(label)
    return matched


def get_red_flags_faq_response() -> str:
    """
    Текст ответа на вопрос «что такое ред флаги» / «ред флаг что это»:
    краткое пояснение + структурированный список красных флагов для озвучки и отображения.
    """
    intro = (
        "Красные флаги — это признаки, при которых нужно срочно обратиться к врачу или вызвать скорую 103. "
        "Вот список таких признаков:\n\n"
    )
    lines = []
    for i, (label, _) in enumerate(RED_FLAG_RULES, 1):
        lines.append(f"{i}. {label}.")
    return intro + "\n".join(lines) + "\n\nИнформация носит справочный характер и не заменяет консультацию врача."


def screen_user_input(
    user_message: str,
    symptom_entries: Optional[list] = None,
    *,
    profile_address: str = "",
):
    # Returns: (is_red_flag, response_text, matched_flags, extra_structured)
    """
    Проверяет сообщение пользователя и последние записи симптомов на красные флаги.
    Возвращает (is_red_flag, response_text, matched_flags, extra_structured).
    Если is_red_flag True — response_text готовый ответ и extra_structured может содержать ambulance_offer_flow.
    """
    texts_to_check = [user_message] if user_message else []
    if symptom_entries:
        for e in symptom_entries[-5:]:  # последние 5 записей
            t = e.get("text") if isinstance(e, dict) else str(e)
            if t:
                texts_to_check.append(t)
    for t in texts_to_check:
        matched = screen_red_flags(t)
        severity_ctx = build_symptom_severity_context(t, "")
        severity_matches = [
            str(x.get("title") or "").strip()
            for x in (severity_ctx.get("red_flag_matches") or [])
            if str(x.get("title") or "").strip()
        ]
        combined = []
        seen = set()
        for item in matched + severity_matches:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            combined.append(item)
        if combined:
            addr = " ".join(str(profile_address or "").split())
            return (
                True,
                _contextual_red_response(t, profile_address=addr),
                combined,
                ambulance_offer_flow_payload(addr),
            )
    return False, None, [], {}
