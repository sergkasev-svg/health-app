from __future__ import annotations

import re
from typing import Any

from app.services.online_medical_retrieval import compose_online_reference_tail
from app.services.weight_strategy_engine import FIND_THE_BLOCK_REPLY_RU as WEIGHT_LOSS_PLATEAU_CANONICAL_REPLY_RU
from app.services.weight_strategy_engine import compose_weight_loss_branch_reply


def _join_lines(items: list[str], prefix: str = "- ") -> str:
    return "\n".join([prefix + str(x).strip() for x in items if str(x).strip()])


def _is_endocrine_hmf_context(payload: dict[str, Any]) -> bool:
    blob = _norm_ctx(
        " ".join(
            [
                str(payload.get("chief_complaint") or ""),
                str(payload.get("user_message") or ""),
                str(payload.get("conversation_context") or ""),
            ]
        )
    )
    has_hormone = any(x in blob for x in ("гормон", "щитовид", "эндокрин", "ттг", "пролактин"))
    has_mood = any(x in blob for x in ("настроен", "перепад", "скачет", "апат", "тревог", "раздраж"))
    has_fatigue = any(x in blob for x in ("устал", "слабост", "нет сил", "энерг"))
    return has_hormone and has_mood and has_fatigue


def _endocrine_concise_repair_response() -> str:
    return (
        "Извините, вы правы — ответ ушёл в сторону. Возвращаюсь к вашему эндокринному сценарию.\n"
        "Короткий план:\n"
        "- вероятнее всего: гормональный фактор + дефициты + влияние сна/стресса;\n"
        "- первый этап: ТТГ, св.Т4, ОАК, ферритин, B12, витамин D, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца);\n"
        "- до результатов: сон 7-8 часов, регулярное питание, щадящая нагрузка, без самоназначения гормонов;\n"
        "- если результаты уже готовы, загрузите их в раздел «Анализы» — помогу с интерпретацией."
    )


def _critic_validate_response(response: str, payload: dict[str, Any]) -> tuple[bool, str]:
    if not _is_endocrine_hmf_context(payload):
        return True, "ok_non_endocrine"
    r = _norm_ctx(response or "")
    ctx = _norm_ctx(
        " ".join(
            [
                str(payload.get("chief_complaint") or ""),
                str(payload.get("user_message") or ""),
                str(payload.get("conversation_context") or ""),
            ]
        )
    )
    if any(x in ctx for x in ("уже говорил", "недел", "неделю", "месяц", "дней")) and (
        "как давно появились симптомы" in r or "как давно это длится" in r
    ):
        return False, "repeat_duration"
    if any(x in ctx for x in ("не про кашель", "ни при чем", "не про температуру", "температуры нет")) and any(
        x in r for x in ("кашель", "температур", "горле", "одыш")
    ):
        return False, "respiratory_drift"
    if any(x in r for x in ("клинический план:", "когда нет сил даже встать с кровати", "базовый набор")):
        return False, "generic_fatigue_drift"
    return True, "ok"


def _critic_attempt_repair(reason: str, response: str, payload: dict[str, Any]) -> str:
    out = str(response or "").strip()
    if not out:
        return _endocrine_concise_repair_response()
    if reason == "repeat_duration":
        out = re.sub(
            r"(?is)\s*[-•]?\s*как давно (появились симптомы|это длится)\??\s*",
            " ",
            out,
        ).strip()
        if out:
            return out
        return _endocrine_concise_repair_response()
    if reason == "respiratory_drift":
        out = re.sub(r"(?is)\b(кашель|температур\w*|горле|одыш\w*)\b", "", out)
        out = re.sub(r"\s{2,}", " ", out).strip(" .,\n\t")
        if out:
            return out
        return _endocrine_concise_repair_response()
    if reason == "generic_fatigue_drift":
        return _endocrine_concise_repair_response()
    return _endocrine_concise_repair_response()


def _answer_with_critic(response: str, payload: dict[str, Any]) -> str:
    current = str(response or "").strip()
    attempts: list[dict[str, Any]] = []
    ok, reason = _critic_validate_response(current, payload)
    attempts.append({"attempt": 0, "ok": bool(ok), "reason": reason})
    if ok:
        payload["_critic_meta"] = {
            "attempts_total": 1,
            "repair_success_at_1": False,
            "fallback_used": False,
            "last_reason": reason,
            "attempts": attempts,
        }
        return current
    repair_success_at_1 = False
    for idx in (1, 2):
        current = _critic_attempt_repair(reason, current, payload)
        ok, reason = _critic_validate_response(current, payload)
        attempts.append({"attempt": idx, "ok": bool(ok), "reason": reason})
        if ok:
            if idx == 1:
                repair_success_at_1 = True
            payload["_critic_meta"] = {
                "attempts_total": idx + 1,
                "repair_success_at_1": repair_success_at_1,
                "fallback_used": False,
                "last_reason": reason,
                "attempts": attempts,
            }
            return current
    payload["_critic_meta"] = {
        "attempts_total": 3,
        "repair_success_at_1": False,
        "fallback_used": True,
        "last_reason": reason,
        "attempts": attempts,
    }
    return _endocrine_concise_repair_response()


def _with_online_sources(response: str, payload: dict[str, Any]) -> str:
    base = str(response or "").strip()
    if not base:
        return base
    if "Проверенные онлайн-источники по теме:" in base:
        return base
    low = _norm_ctx(base)
    # Do not bloat short repair/apology responses with links.
    if (
        len(base) <= 900
        and any(
            k in low
            for k in (
                "извините",
                "ответ получился с повторами",
                "ответ ушёл в сторону",
                "короткому и конкретному плану",
            )
        )
    ):
        return base
    tail = compose_online_reference_tail(payload)
    if not tail:
        return base
    return (base + "\n\n" + tail).strip()


_HYPOTHESIS_ID_RU: dict[str, str] = {
    "knee_overuse": "перегрузка колена (без острой травмы)",
    "knee_contusion": "ушиб / удар по колену",
    "knee_sprain": "растяжение связок колена",
    "ankle_sprain": "растяжение связок голеностопа",
    "ankle_contusion": "ушиб голеностопа",
    "shoulder_impingement": "боль в плече при движении (импинджмент)",
    "back_strain": "напряжение мышц спины",
}


def _hypothesis_display_ru(h: dict[str, Any] | None) -> str:
    if not h:
        return ""
    label = str(h.get("label_ru") or "").strip()
    if label and not re.fullmatch(r"[a-z][a-z0-9_]*", label, flags=re.I):
        return label
    name = str(h.get("name") or "").strip()
    if name and not re.fullmatch(r"[a-z][a-z0-9_]*", name, flags=re.I):
        return name
    hid = str(h.get("id") or "").strip().lower()
    if hid in _HYPOTHESIS_ID_RU:
        return _HYPOTHESIS_ID_RU[hid]
    if hid and re.fullmatch(r"[a-z][a-z0-9_]*", hid, flags=re.I):
        return hid.replace("_", " ")
    return hid or ""


def _ctx_msk_injury(t: str) -> bool:
    return any(
        k in t
        for k in (
            "колен",
            "ног",
            "сустав",
            "лодыж",
            "голеностоп",
            "плеч",
            "спин",
            "наступ",
            "ушиб",
            "ударил",
            "удар ",
            " удар",
            "упал",
            "травм",
            "паден",
            "подвернул",
        )
    )


def _question_is_oral_dental(q: str) -> bool:
    ql = (q or "").strip().lower()
    return any(x in ql for x in ("зуб", "десн", "жеват", "полости рта", "полость рта", "во рту"))


def _self_care_line_is_dental(line: str) -> bool:
    xl = (line or "").strip().lower()
    return any(x in xl for x in ("жеват", "зуб", "полости рта", "десн", "гигиену полости рта"))


def _pick_first_msk_compatible_question(questions: list[Any], ctx: str) -> str:
    t = _norm_ctx(ctx)
    msk = _ctx_msk_injury(t)
    for q in questions or []:
        tq = str((q or {}).get("text") or "").strip()
        if not tq:
            continue
        if msk and _question_is_oral_dental(tq):
            continue
        if not _question_redundant_for_context(tq, ctx):
            return tq
    for q in questions or []:
        tq = str((q or {}).get("text") or "").strip()
        if tq and not (msk and _question_is_oral_dental(tq)):
            return tq
    return ""


def _filter_self_care_msk(items: list[str], ctx: str) -> list[str]:
    t = _norm_ctx(ctx)
    if not _ctx_msk_injury(t):
        return list(items)[:3]
    out: list[str] = []
    for x in items or []:
        if _self_care_line_is_dental(str(x)):
            continue
        s = str(x).strip()
        if s:
            out.append(s)
        if len(out) >= 3:
            break
    return out if out else [str(x).strip() for x in (items or [])[:3] if str(x).strip()]


def _user_context_blob(case_state: dict[str, Any] | None) -> str:
    """Текст жалобы пользователя из состояния кейса (чтобы не спрашивать то, что уже сказано)."""
    if not case_state:
        return ""
    parts = [
        str(case_state.get("chief_complaint") or ""),
        str(case_state.get("conversation_context") or ""),
        str(case_state.get("user_message") or ""),
        str(case_state.get("normalized_text") or ""),
        str(case_state.get("complaint_hint") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _norm_ctx(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _ctx_has_fever(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    if re.search(r"\b3[6-9]\d?[.,]?\d*\b", t):
        return True
    if re.search(r"\d{1,2}[.,]\d*\s*°", t):
        return True
    return any(k in t for k in ("температур", "субфебрил", "жар", "лихорад", " °"))


def _ctx_has_cough(ctx: str) -> bool:
    return "каш" in _norm_ctx(ctx)


def _ctx_has_dyspnea(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("одыш", "тяжело дыш", "не хватает воздух", "задых"))


def _ctx_denies_dyspnea(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(
        k in t
        for k in (
            "одышки нет",
            "без одышки",
            "не одышка",
            "нет одышки",
            "воздуха хватает",
            "воздух хватает",
            "воздуха достаточно",
            "дышу нормально",
            "легко дышу",
            "дышать нормально",
            "нет нехватки воздух",
        )
    )


def _ctx_has_sputum_or_runny(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("мокрот", "отхарк", "сопл", "насморк"))


def _ctx_has_throat(ctx: str) -> bool:
    return any(k in _norm_ctx(ctx) for k in ("горл", "глотат", "фаринг", "ангин"))


def _ctx_has_neuro_warn(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(
        k in t
        for k in (
            "онемен",
            "слабост",
            "перекос",
            "реч",
            "зрение",
            "не могу поднять",
            "не двигается",
            "половин",
        )
    )


def _ctx_has_trauma(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("удар", "паден", "травм", "ушиб"))


def _ctx_has_swelling(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("отёк", "отек", "опух", "припух"))


def _ctx_has_gi_pain_loc(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("живот", "эпигаст", "подребер", "внизу жив", "справа", "слева"))


def _ctx_has_vomit_diarrhea(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("рвот", "тошнит", "понос", "диаре", "жидкий стул"))


def _ctx_has_chest_pain(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("груд", "давит в груди", "боль в груди", "жмет в груди"))


def _ctx_has_rash_itch(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("сып", "зуд", "крапив", "волдыр", "пятн"))


def _ctx_has_dental_swallow(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    return any(k in t for k in ("десн", "зуб", "глотат", "открыть рот", "щек", "флюс"))


def _question_redundant_for_context(question: str, ctx: str) -> bool:
    """True, если ответ на вопрос уже содержится в жалобе пользователя."""
    ql = (question or "").strip().lower()
    if not ql:
        return True
    if ("температур" in ql or "озноб" in ql) and _ctx_has_fever(ctx):
        return True
    if ("кашель" in ql or "кашл" in ql) and _ctx_has_cough(ctx):
        if "мокрот" in ql and not _ctx_has_sputum_or_runny(ctx):
            pass
        else:
            return True
    if ("мокрот" in ql or "мокрота" in ql) and _ctx_has_sputum_or_runny(ctx):
        return True
    if ("одыш" in ql or "нехватк" in ql) and (_ctx_has_dyspnea(ctx) or _ctx_denies_dyspnea(ctx)):
        return True
    if ("горло" in ql or "глотать" in ql) and _ctx_has_throat(ctx):
        return True
    if ("слабость" in ql or "онемен" in ql) and _ctx_has_neuro_warn(ctx):
        return True
    if ("удар" in ql or "паден" in ql) and _ctx_has_trauma(ctx):
        return True
    if ("отёк" in ql or "отек" in ql) and _ctx_has_swelling(ctx):
        return True
    if "где именно" in ql and _ctx_has_gi_pain_loc(ctx):
        return True
    if ("рвот" in ql or "понос" in ql or "диаре" in ql) and _ctx_has_vomit_diarrhea(ctx):
        return True
    if ("груд" in ql) and _ctx_has_chest_pain(ctx):
        return True
    if ("сыпь" in ql or "зуд" in ql) and _ctx_has_rash_itch(ctx):
        return True
    if ("десн" in ql or "щек" in ql or "глотать" in ql or "рот" in ql) and _ctx_has_dental_swallow(ctx):
        return True
    if any(
        k in ql
        for k in (
            "как давно",
            "сколько длится",
            "когда появились",
            "появились симптомы",
            "давно ли",
            "сколько времени",
        )
    ) and _ctx_has_symptom_duration(ctx):
        return True
    return False


def _user_frustration(t: str) -> bool:
    return any(
        k in t
        for k in (
            "бесконеч",
            "по кругу",
            "повторя",
            "уже говорил",
            "уже сказал",
            "не в ту сторон",
            "надоело",
            "совсем не туда",
            "попутал",
            "не устраивает",
            "игнор",
            "кидаешь",
            "туфта",
            "один вопрос",
            "три вопроса",
            "пять вопросов",
        )
    )


def _ctx_has_symptom_duration(ctx: str) -> bool:
    t = _norm_ctx(ctx)
    if re.search(r"\b[1-9]\d?\s*(?:дн|дня|дней|сут(?:ок|ка)?|час(?:а|ов)?|недел|месяц)", t):
        return True
    if re.search(r"(?:^|[^\d])3\s*(?:дн|дня|дней)", t):
        return True
    return any(
        k in t
        for k in (
            "три дня",
            "третий день",
            "уже третий",
            "несколько дн",
            "всего несколько",
            "пару дней",
            "пара дней",
            "мало дней",
            "последние три",
            "трое сут",
            "симптомы уже",
            "уже отвечал",
            "день подряд",
            "всего дня",
            "всего два",
        )
    )


def _payload_context_blob(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    parts = [
        str(payload.get("chief_complaint") or ""),
        str(payload.get("conversation_context") or ""),
        str(payload.get("user_message") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _acute_febrile_respiratory(ctx: str, evidence_present: set[str]) -> bool:
    t = _norm_ctx(ctx)
    markers = {"cough", "sore_throat", "runny_nose", "sputum", "dyspnea"}
    resp_ev = markers & evidence_present
    resp_lex = sum(1 for k in ("каш", "мокрот", "сопл", "насморк", "горл", "орви", "простуд", "дыхател", "лор") if k in t)
    has_resp = len(resp_ev) >= 2 or resp_lex >= 2 or (len(resp_ev) >= 1 and resp_lex >= 1)
    has_fever = _ctx_has_fever(t) or "fever" in evidence_present
    return has_resp and has_fever


def _compose_acute_febrile_uri_reply(*, interpretation: str, ctx: str) -> str:
    parts: list[str] = []
    intr = (interpretation or "").strip()
    if intr:
        parts.append(intr)
    parts.append(
        "По описанию картина в первую очередь похожа на острую респираторную инфекцию (например, ОРВИ) "
        "с вовлечением носа и горла; при кашле с мокротой возможен и бронхит, но это подтверждает только очный осмотр."
    )
    parts.append(
        "Температура около 39–39,5 °C и симптомы несколько дней — разумный повод очно обратиться к терапевту или вызвать врача на дом "
        "для осмотра и при необходимости анализов и назначения лечения."
    )
    parts.append(
        "До приёма: отдых, много жидкости, проветривание; жаропонижающие — по инструкции при необходимости. "
        "При ухудшении дыхания, боли в груди, спутанности сознания или сильной слабости — скорая (103)."
    )
    body = "\n\n".join(parts)
    t = _norm_ctx(ctx)
    tail = ""
    if not _ctx_has_dyspnea(t) and not _ctx_denies_dyspnea(t) and "одыш" not in t and "не хватает воздух" not in t:
        tail = "\n\nУточню один момент:\n- Есть ли одышка, боль или тяжесть в груди?"
    elif not _ctx_has_neuro_warn(ctx):
        tail = "\n\nУточню один момент:\n- Нет ли сильной вялости, спутанности или невозможности пить?"
    return (body + tail).strip()


# Эталонный ответ на доминирующую астению/«нет сил встать» без респираторного кластера (ветка fatigue_deficiency).
CONSTITUTIONAL_FATIGUE_CANONICAL_REPLY_RU = """Когда нет сил даже встать с кровати и ничего не хочется — это не лень и не «просто устал». Это состояние, которое обычно связано с перегрузкой организма или психики.

Что это может быть:
— часто: сильный стресс или выгорание
— также: проблемы со сном
— возможно: дефициты (железо, B12, витамин D)
— иногда: гормональные причины (щитовидка)
— реже: последствия инфекции

Важно: такие состояния почти всегда имеют причину, и её можно найти.

Что делать сейчас:
— не заставляйте себя через силу (это может ухудшить состояние)
— базово: сон, вода, регулярное питание
— минимальная активность по самочувствию (даже выйти на 5–10 минут — уже нормально)

Что стоит проверить:
— общий анализ крови
— ферритин
— витамин B12
— витамин D
— ТТГ

Обратиться к врачу стоит, если:
— это длится больше 1–2 недель
— становится хуже
— появляются сильная тревога, апатия или потеря интереса к жизни

На всякий пожарный, можно сдать следующие анализы:
БАЗОВЫЙ НАБОР (с чего начать)

👉 этого достаточно в 80% случаев усталости:

🩸 Кровь
Общий анализ крови (ОАК)
Ферритин (запасы железа)
Витамин B12
Витамин D
🧠 Гормоны
ТТГ (щитовидка)
👉 Почему именно это:
анемия / железо → частая причина слабости
B12 → энергия и нервная система
витамин D → усталость, иммунитет
ТТГ → замедление организма
После интерпретации результатов анализов, к врачу для принятия решения."""

# Начало эталона (стабильная строка): по ней отрезаем дублирующий «Клинический план» после генерации.
CONSTITUTIONAL_FATIGUE_CANONICAL_LEAD_PREFIX = "Когда нет сил даже встать с кровати"

# Боль в груди при глубоком дыхании + нехватка воздуха — единый безопасный ответ (без «давление/пульс» в первую очередь).
PLEURITIC_CHEST_DYSPNEA_CANONICAL_REPLY_RU = """Слышу вас.

Боль в груди, которая усиливается при дыхании, и ощущение нехватки воздуха — это симптомы, которые нужно воспринимать серьёзно.

Что это может быть:
— возможно: воспаление дыхательных путей или плевры
— иногда: мышечная боль
— важно исключить: проблемы с сердцем или тромб в лёгких

Риск сейчас: средний → может быть высоким

Что сделать прямо сейчас:
— прекратите любую нагрузку
— сядьте или лягте в удобное положение
— старайтесь дышать спокойно

Важно:
если боль в груди сохраняется и есть ощущение, что не хватает воздуха — лучше не ждать

Срочно вызывайте помощь (103/112), если:
— становится трудно дышать даже в покое
— боль усиливается или давит
— появляется слабость, головокружение или холодный пот
— боль отдаёт в руку, спину или челюсть

Даже если это окажется неопасной причиной, такие симптомы лучше проверить очно как можно быстрее."""

PLEURITIC_CHEST_DYSPNEA_CANONICAL_LEAD_PREFIX = "Слышу вас."

CANONICAL_NO_EXTRA_CLINICAL_PLAN_LEADS: tuple[str, ...] = (
    CONSTITUTIONAL_FATIGUE_CANONICAL_LEAD_PREFIX,
    PLEURITIC_CHEST_DYSPNEA_CANONICAL_LEAD_PREFIX,
)


def response_has_canonical_no_clinical_plan_lead(text: str) -> bool:
    """Ответы-эталоны без доп. блока «Клинический план»."""
    b = (text or "").replace("\r\n", "\n")
    return any(lead in b for lead in CANONICAL_NO_EXTRA_CLINICAL_PLAN_LEADS)


# Вступление по ветке (один вопрос ниже отдельной строкой; без повтора «уточню»).
BRANCH_INTROS: dict[str, str] = {
    "orthopedics": "Понял. Нужно аккуратно отличить перегрузку от возможной травмы.",
    "ortho": "Понял. Нужно аккуратно отличить перегрузку от возможной травмы.",
    "oral_cavity": "Понял. Оценим, насколько это похоже на локальную проблему полости рта или зуба.",
    "respiratory": "Понял. Оценим дыхательные симптомы и общее состояние.",
    "throat": "Понял. Оценим дыхательные симптомы и общее состояние.",
    "gastro": "Понял. Нужно сузить картину по животу.",
    "abdomen": "Понял. Нужно сузить картину по животу.",
    "cardio": "Понял. Такие жалобы важно уточнить аккуратно.",
    "neuro": "Понял. При головной боли важно не пропустить тревожные неврологические признаки.",
    "head": "Понял. При головной боли важно не пропустить тревожные неврологические признаки.",
    "urinary": "Понял. Оценим мочевые симптомы.",
    "fatigue_deficiency": (
        "Когда нет сил даже встать с кровати и ничего не хочется — это не лень и не «просто устал». "
        "Это состояние, которое обычно связано с перегрузкой организма или психики."
    ),
    "pleuritic_chest_dyspnea": "Слышу вас. Боль в груди при дыхании с ощущением нехватки воздуха нужно оценивать серьёзно.",
    "weight_loss_plateau": "Слышу вас. Если вес не снижается длительно при попытках снизить его — это повод навести порядок в базовых вещах и при необходимости проверить анализы.",
    "general": "Понял. Пока мало данных, чтобы сузить причину.",
    "allergy_skin": "Понял. Нужно понять, насколько это похоже на кожную реакцию или аллергию.",
    "skin": "Понял. Нужно понять, насколько это похоже на кожную реакцию или аллергию.",
}

# Кандидаты по приоритету; из жалобы убираются уже «отвеченные», остаётся один вопрос за ответ.
BRANCH_QUESTION_CANDIDATES: dict[str, list[str]] = {
    "orthopedics": [
        "Был ли удар, падение или резкое движение, после которого началась боль?",
        "Есть ли отёк или припухлость в области сустава?",
        "Можете ли без резкого усиления боли наступать на ногу или сгибать/разгибать сустав?",
    ],
    "ortho": [
        "Был ли удар, падение или резкое движение, после которого началась боль?",
        "Есть ли отёк или припухлость в области сустава?",
        "Можете ли без резкого усиления боли наступать на ногу или сгибать/разгибать сустав?",
    ],
    "oral_cavity": [
        "Есть ли отёк десны или щёки, гнойный привкус или усиление боли при жевании?",
        "Есть ли температура или невозможность открыть рот из-за боли?",
        "Трудно ли глотать слюну или есть ли боль при открывании рта?",
    ],
    "respiratory": [
        "Есть ли температура или озноб?",
        "Есть ли кашель и мокрота?",
        "Есть ли одышка или чувство нехватки воздуха?",
    ],
    "throat": [
        "Есть ли температура или озноб?",
        "Есть ли кашель и мокрота?",
        "Есть ли одышка или чувство нехватки воздуха?",
    ],
    "gastro": [
        "Где именно локализуется дискомфорт (вверху живота, вокруг пупка, справа внизу)?",
        "Есть ли рвота, понос или чёрный/кровяной стул?",
        "Есть ли температура?",
    ],
    "abdomen": [
        "Где именно локализуется дискомфорт (вверху живота, вокруг пупка, справа внизу)?",
        "Есть ли рвота, понос или чёрный/кровяной стул?",
        "Есть ли температура?",
    ],
    "cardio": [
        "Есть ли боль, давление или жжение за грудиной?",
        "Есть ли одышка в покое или при нагрузке?",
        "Кружится ли голова или есть ли выраженная слабость вместе с дискомфортом в груди?",
    ],
    "neuro": [
        "Есть ли слабость в руке или ноге, онемение, перекос лица, спутанность речи или нарушение зрения?",
        "Есть ли температура 38 °C и выше или сильный озноб? (если уже называли число — напишите, держится ли жар.)",
        "Головная боль нарастала постепенно или возникла внезапно «как удар»? Есть ли тошнота или непереносимость яркого света?",
    ],
    "head": [
        "Есть ли слабость в руке или ноге, онемение, перекос лица, спутанность речи или нарушение зрения?",
        "Есть ли температура 38 °C и выше или сильный озноб? (если уже называли число — напишите, держится ли жар.)",
        "Головная боль нарастала постепенно или возникла внезапно «как удар»? Есть ли тошнота или непереносимость яркого света?",
    ],
    "urinary": [
        "Есть ли температура или озноб?",
        "Есть ли боль в пояснице или при мочеиспускании?",
        "Замечали ли кровь или необычный цвет/запах мочи?",
    ],
    "fatigue_deficiency": [
        "Чтобы сузить причину, ответьте коротко по пунктам: как давно такое состояние; как спите (насыпаетесь или просыпаетесь раньше); был ли сильный стресс или болезнь незадолго до этого?",
        "Есть ли температура, одышка в покое, похудение без диеты или сильная тревога/подавленность?",
        "Были ли недавно анализы крови (гемоглобин, ферритин, B12, витамин D, ТТГ)?",
    ],
    "pleuritic_chest_dyspnea": [
        "Как давно это началось и было ли что-то необычное перед этим: перелёт, длительное сидение, травма грудной клетки, лихорадка или кашель?",
        "Есть ли боль или отёк в икре, односторонняя отёчность ноги или внезапная одышка без грудной боли?",
        "Есть ли внезапная слабость, обморок, холодный пот или боль, отдающая в руку, шею или челюсть?",
    ],
    "weight_loss_plateau": [
        "Что ближе к вам сейчас: усталость и «без напряга», любовь к цифрам и контролю, частые срывы от стресса, ощущение что «всё делаю, а вес стоит», или нужен быстрый старт?",
        "Какой у вас рост и вес сейчас (или ИМТ, если знаете) и менялся ли объём талии за последние месяцы?",
        "Сдавали ли недавно глюкозу/инсулин, ТТГ, ферритин и витамин D?",
    ],
    "general": [
        "Как давно это длится и как быстро меняется?",
        "Есть ли температура, одышка или сильная слабость?",
        "Что уже пробовали и было ли облегчение?",
    ],
    "allergy_skin": [
        "Есть ли сыпь или только зуд без сыпи?",
        "Отекали ли губы, язык или веко? Было ли трудно дышать?",
        "Связано ли это с приёмом пищи, лекарств или укусом насекомого?",
    ],
    "skin": [
        "Есть ли сыпь или только зуд без сыпи?",
        "Отекали ли губы, язык или веко? Было ли трудно дышать?",
        "Связано ли это с приёмом пищи, лекарств или укусом насекомого?",
    ],
}

# Совместимость: старый код мог проверять ключ в BRANCH_FALLBACK
BRANCH_FALLBACK = BRANCH_INTROS


def _pick_one_branch_question(branch: str, case_state: dict[str, Any] | None) -> str:
    ctx = _user_context_blob(case_state)
    pool: list[str] = []
    for q in (case_state or {}).get("next_questions") or []:
        t = str((q or {}).get("text") or "").strip()
        if t:
            pool.append(t)
            break
    pool.extend(BRANCH_QUESTION_CANDIDATES.get(branch, []))
    for q in pool:
        if q and not _question_redundant_for_context(q, ctx):
            return q
    return "Что усиливает симптомы и что немного облегчает?"


def compose_branch_fallback(branch: str, case_state: dict[str, Any] | None) -> str:
    """Один уточняющий вопрос по ветке; не дублирует то, что уже сказано в жалобе."""
    branch = (branch or "").strip()
    if branch == "fatigue_deficiency":
        return CONSTITUTIONAL_FATIGUE_CANONICAL_REPLY_RU.strip()
    if branch == "pleuritic_chest_dyspnea":
        return PLEURITIC_CHEST_DYSPNEA_CANONICAL_REPLY_RU.strip()
    if branch == "weight_loss_plateau":
        return compose_weight_loss_branch_reply(case_state).strip()
    intro = BRANCH_INTROS.get(branch, "").strip() or "Понял."
    q = _pick_one_branch_question(branch, case_state)
    return f"{intro}\n\n- {q}"


def compose_oral_branch(
    *,
    interpretation: str,
    top_hypotheses: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    self_care: list[str],
) -> str:
    """Compose response for oral-cavity branch from latest state."""
    lead = top_hypotheses[0] if top_hypotheses else {}
    second = top_hypotheses[1] if len(top_hypotheses) > 1 else {}
    lead_name = str(lead.get("label_ru") or lead.get("name") or "стоматологическая причина").strip()
    second_name = str(second.get("label_ru") or second.get("name") or "").strip()

    intro = "По описанию это больше похоже на проблему полости рта или зуба, а не на случайный временный дискомфорт."
    parts = []
    if interpretation:
        parts.append(interpretation)
    parts.append(intro)
    parts.append("\nСейчас в приоритете:\n- " + lead_name)
    if second_name:
        parts.append("- " + second_name)
    parts.append("\nЧтобы оценить серьёзность, уточню:")
    q_texts = [str(q.get("text") or "").strip() for q in (questions or [])[:1] if str(q.get("text") or "").strip()]
    parts.append(("\n".join("- " + t for t in q_texts) if q_texts else ""))
    if self_care:
        parts.append("\nПока можно:\n" + "\n".join("- " + str(x).strip() for x in self_care[:3]))
    return "\n\n".join(p for p in parts if p).strip()


def compose_from_case_state_simple(case_state: dict[str, Any]) -> str:
    """Universal composer from case_state (stage1): intro + lead hypothesis + questions."""
    hypotheses = case_state.get("top_hypotheses", [])
    questions = list(case_state.get("next_questions") or [])

    if not questions:
        scenario_match = case_state.get("scenario_match")
        if scenario_match and isinstance(scenario_match.get("must_ask"), list):
            questions = [{"id": f"q_{i}", "text": str(s).strip()} for i, s in enumerate(scenario_match["must_ask"]) if str(s).strip()]

    intro = "Понял описание вашей ситуации."

    if hypotheses:
        lead = hypotheses[0].get("id", "")
        if lead:
            intro += f"\nСейчас наиболее вероятно: {lead}."

    q = "\n".join(f"- {x.get('text', '')}" for x in questions[:1] if x.get("text"))

    return intro + "\n\nЧтобы понять точнее, уточню:\n" + (q or "- Нет дополнительных вопросов.")


def compose_from_case_state(case_state: dict[str, Any]) -> str:
    """Build response from full case_state; routes to oral branch, branch fallback or generic dynamic response."""
    evidence_present = {str(x).strip() for x in (case_state.get("evidence_present") or []) if str(x).strip()}
    body_regions = list(case_state.get("body_regions") or [])
    hypotheses = case_state.get("top_hypotheses") or []
    questions = case_state.get("next_questions") or []

    branch = ""
    if body_regions:
        r = body_regions[0]
        if r in (
            "orthopedics",
            "respiratory",
            "gastro",
            "cardio",
            "neuro",
            "urinary",
            "fatigue_deficiency",
            "pleuritic_chest_dyspnea",
            "weight_loss_plateau",
            "allergy_skin",
            "oral_cavity",
        ):
            branch = r
        elif r in ("knee", "ankle", "back", "shoulder"):
            branch = "orthopedics"
        elif r in ("throat", "lungs"):
            branch = "respiratory"
        elif r == "abdomen":
            branch = "gastro"
        elif r in ("head",):
            branch = "neuro"
        elif r == "general":
            branch = "fatigue_deficiency"
        elif r == "skin":
            branch = "allergy_skin"
        else:
            branch = r

    full_ctx = _user_context_blob(case_state)
    if "pleuritic_chest_dyspnea" in evidence_present:
        branch = "pleuritic_chest_dyspnea"
    elif "weight_loss_plateau" in evidence_present:
        branch = "weight_loss_plateau"
    if branch in ("orthopedics", "ortho", "neuro", "head") and _acute_febrile_respiratory(full_ctx, evidence_present):
        branch = "respiratory"

    if branch == "pleuritic_chest_dyspnea":
        return compose_branch_fallback("pleuritic_chest_dyspnea", case_state)

    if branch == "weight_loss_plateau":
        return compose_branch_fallback("weight_loss_plateau", case_state)

    if hypotheses and questions:
        lead = hypotheses[0].get("id", "основная гипотеза")
        picked = ""
        for x in questions:
            tq = str(x.get("text") or "").strip()
            if tq and not _question_redundant_for_context(tq, full_ctx):
                picked = tq
                break
        if not picked:
            picked = str(questions[0].get("text") or "").strip()
        q = f"- {picked}" if picked else ""
        return (
            "Понял.\n\n"
            f"Сейчас в первую очередь рассматривается: {lead}.\n\n"
            "Чтобы понять точнее, уточню:\n"
            f"{q}"
        ).strip()

    if branch and branch in BRANCH_FALLBACK:
        return compose_branch_fallback(branch, case_state)

    is_oral = "oral" in body_regions or "oral_cavity" in body_regions or bool(
        evidence_present
        & {
            "tooth_pain",
            "gum_swelling",
            "gum_bleeding",
            "mouth_ulcer",
            "tongue_pain",
            "jaw_pain",
            "bad_breath",
            "dry_mouth",
            "facial_swelling",
            "oral_white_patch",
            "post_dental_extraction",
        }
    )

    top_hypotheses = list(case_state.get("top_hypotheses") or [])
    next_questions = list(case_state.get("next_questions") or [])
    red_flags = list(case_state.get("red_flags_detected") or [])
    care_level = str(case_state.get("care_level") or "").strip()
    detail = str(case_state.get("care_level_detail") or care_level or "").strip()

    self_care: list[str] = []
    for h in top_hypotheses[:2]:
        self_care.extend(h.get("safe_actions") or [])
    self_care = list(dict.fromkeys(self_care))[:4]

    interpretation = "Понял."
    if is_oral:
        interpretation = "Понял. По вашему описанию это похоже на ситуацию, связанную с полостью рта или зубами."

    if red_flags:
        urgent_intro = (
            "Есть признаки, при которых нужна срочная очная оценка."
            if detail == "urgent_clinical_assessment"
            else "Есть признаки, при которых лучше не тянуть с очной оценкой."
        )
        return (
            (interpretation + "\n\n" if interpretation else "")
            + urgent_intro
            + "\n\nЧтобы быстро оценить риск, уточню:\n"
            + _join_lines([str(q.get("text") or "") for q in next_questions[:1]])
            + ("\n\nДо осмотра:\n" + _join_lines(self_care[:3]) if self_care else "")
        ).strip()

    if is_oral:
        return compose_oral_branch(
            interpretation=interpretation,
            top_hypotheses=top_hypotheses,
            questions=next_questions,
            self_care=self_care,
        )

    if not top_hypotheses and _acute_febrile_respiratory(full_ctx, evidence_present) and (
        _ctx_has_symptom_duration(full_ctx) or _user_frustration(_norm_ctx(full_ctx))
    ):
        apol = ""
        if _user_frustration(_norm_ctx(full_ctx)):
            apol = "Понял вас, извините за повторы — ориентируюсь на всё, что вы уже описали.\n\n"
        return apol + _compose_acute_febrile_uri_reply(interpretation=interpretation, ctx=full_ctx).strip()

    payload = {
        "interpretation": interpretation,
        "top_hypotheses": top_hypotheses,
        "red_flags": [{"message": m} for m in red_flags],
        "next_questions": next_questions,
        "self_care": self_care,
        "care_level": care_level,
        "evidence_present": list(evidence_present),
        "body_regions": list(case_state.get("body_regions") or []),
        "chief_complaint": str(case_state.get("chief_complaint") or "").strip(),
        "user_message": str(case_state.get("user_message") or case_state.get("normalized_text") or "").strip(),
        "conversation_context": str(case_state.get("conversation_context") or "").strip(),
    }
    return compose_dynamic_response(payload)


def compose_dynamic_response(payload: dict[str, Any]) -> str:
    top = payload.get("top_hypotheses") or []
    red_flags = payload.get("red_flags") or []
    questions = payload.get("next_questions") or []
    self_care = payload.get("self_care") or []
    care_level = str(payload.get("care_level") or "").strip()
    detail = str(payload.get("care_level_detail") or care_level or "").strip()
    interpretation = str(payload.get("interpretation") or "").strip()
    evidence_present = {str(x).strip() for x in (payload.get("evidence_present") or []) if str(x).strip()}

    if red_flags:
        urgent_intro = (
            "Есть признаки, при которых нужна срочная очная оценка."
            if detail == "urgent_clinical_assessment"
            else "Есть признаки, при которых лучше не тянуть с очной оценкой."
        )
        return (
            (interpretation + "\n\n" if interpretation else "")
            + urgent_intro
            + "\n\nЧтобы быстро оценить риск, уточню:\n"
            + _join_lines([str(q.get("text") or "") for q in questions[:1]])
            + ("\n\nДо осмотра:\n" + _join_lines(self_care[:3]) if self_care else "")
        ).strip()

    if not top:
        blob = _payload_context_blob(payload)
        um_extra = str(payload.get("user_message") or "").strip()
        full_ctx = (blob + " " + um_extra).strip()
        if _acute_febrile_respiratory(blob, evidence_present) and (
            _ctx_has_symptom_duration(blob) or _user_frustration(_norm_ctx(blob))
        ):
            apol = ""
            if _user_frustration(_norm_ctx(blob)):
                apol = "Понял вас, извините за повторы — смотрю на всё, что вы уже написали.\n\n"
            return _with_online_sources(apol + _compose_acute_febrile_uri_reply(interpretation=interpretation, ctx=blob).strip(), payload)
        if _user_frustration(_norm_ctx(full_ctx)):
            apol = "Извините, вы правы — ответ получился с повторами. Перехожу к короткому и конкретному плану.\n\n"
            ctx = _norm_ctx(full_ctx)
            has_duration = any(x in ctx for x in ("недел", "месяц", "дн", "дней", "неделю"))
            has_sleep = any(x in ctx for x in ("сплю", "сон", "засып", "просып"))
            has_stress = any(x in ctx for x in ("стресс", "тревог", "перегруз", "выгор"))
            if has_duration and has_sleep and has_stress:
                return _with_online_sources(_answer_with_critic((
                    apol
                    + "Что делать сейчас:\n"
                    + "- первый этап анализов: ОАК, ферритин, B12, витамин D, ТТГ, свободный Т4, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца).\n"
                    + "- режим на 7 дней: сон 7-8 часов, регулярное питание, щадящая нагрузка.\n"
                    + "- гормоны/добавки не начинать до результатов.\n"
                    + "- если уже получили результаты анализов, загрузите их в раздел «Анализы» — помогу с интерпретацией."
                ).strip(), payload), payload)
            pool: list[str] = []
            for q in BRANCH_QUESTION_CANDIDATES.get("fatigue_deficiency", []):
                if q and not _question_redundant_for_context(q, full_ctx):
                    pool.append(q)
            for q in BRANCH_QUESTION_CANDIDATES.get("general", []):
                if q and not _question_redundant_for_context(q, full_ctx):
                    pool.append(q)
            if pool:
                return _with_online_sources(_answer_with_critic((apol + "Один уточняющий вопрос по делу:\n- " + pool[0]).strip(), payload), payload)
            return _with_online_sources(_answer_with_critic((
                apol
                + "Уточните в одной строке: как давно это длится, как спите и был ли выраженный стресс."
            ).strip(), payload), payload)

        body_regions = list(payload.get("body_regions") or [])
        branch = ""
        if body_regions:
            r = body_regions[0]
            if r in (
                "orthopedics",
                "respiratory",
                "gastro",
                "cardio",
                "neuro",
                "urinary",
                "fatigue_deficiency",
                "pleuritic_chest_dyspnea",
                "weight_loss_plateau",
                "allergy_skin",
                "oral_cavity",
            ):
                branch = r
            elif r in ("knee", "ankle", "back", "shoulder"):
                branch = "ortho"
            elif r in ("oral_cavity", "oral"):
                branch = "oral_cavity"
            elif r in ("throat", "lungs"):
                branch = "respiratory"
            elif r == "abdomen":
                branch = "gastro"
            elif r == "cardio":
                branch = "cardio"
            elif r in ("head", "neuro"):
                branch = "neuro"
            elif r == "urinary":
                branch = "urinary"
            elif r == "skin":
                branch = "allergy_skin"
            elif r == "general":
                branch = "fatigue_deficiency"
            else:
                branch = r
        if "pleuritic_chest_dyspnea" in evidence_present:
            branch = "pleuritic_chest_dyspnea"
        elif "weight_loss_plateau" in evidence_present:
            branch = "weight_loss_plateau"
        if branch in ("orthopedics", "ortho", "neuro", "head") and _acute_febrile_respiratory(blob, evidence_present):
            branch = "respiratory"
        if branch and branch in BRANCH_FALLBACK:
            if _is_endocrine_hmf_context(payload) and branch == "fatigue_deficiency":
                return _with_online_sources(_endocrine_concise_repair_response(), payload)
            out = compose_branch_fallback(branch, payload)
            if out:
                if branch in ("fatigue_deficiency", "pleuritic_chest_dyspnea", "weight_loss_plateau"):
                    return _with_online_sources(_answer_with_critic(out.strip(), payload), payload)
                return _with_online_sources(_answer_with_critic((interpretation + "\n\n" + out if interpretation else out).strip(), payload), payload)
        picked = ""
        for q in questions or []:
            tq = str((q or {}).get("text") or "").strip()
            if tq and not _question_redundant_for_context(tq, blob):
                picked = tq
                break
        if not picked and questions:
            fq = str((questions[0] or {}).get("text") or "").strip()
            if fq and not _question_redundant_for_context(fq, blob):
                picked = fq
        if not picked:
            full_ctx = _norm_ctx((blob + " " + str(payload.get("user_message") or "")).strip())
            for q in BRANCH_QUESTION_CANDIDATES.get("fatigue_deficiency", []):
                if q and not _question_redundant_for_context(q, full_ctx):
                    picked = q
                    break
            if not picked:
                for q in BRANCH_QUESTION_CANDIDATES.get("general", []):
                    if q and not _question_redundant_for_context(q, full_ctx):
                        picked = q
                        break
        return _with_online_sources(_answer_with_critic((
            (interpretation + "\n\n" if interpretation else "")
            + "Пока данных недостаточно, чтобы сузить причину.\n\n"
            + ("Уточню один ключевой момент:\n" + _join_lines([picked]) if picked else "Ниже — следующий шаг по сути.")
        ).strip(), payload), payload)

    lead = top[0]
    second = top[1] if len(top) > 1 else None
    lead_name = _hypothesis_display_ru(lead) or str(lead.get("id") or "").strip()
    second_name = (_hypothesis_display_ru(second) if second else "") or ""
    blob_ortho = _payload_context_blob(payload)
    t_ortho = _norm_ctx(blob_ortho)
    has_trauma = bool({"fall_impact", "knee_trauma", "direct_blow"} & evidence_present) or any(
        k in t_ortho for k in ("упал", "ударил", "травм", "ушиб", "паден", "удар по", "удар колен")
    )
    region_label = "опорно-двигательной системы"
    if {"knee_pain"} & evidence_present:
        region_label = "колена"
    elif {"ankle_pain"} & evidence_present:
        region_label = "голеностопа"
    elif {"shoulder_pain"} & evidence_present:
        region_label = "плеча"
    elif {"back_pain"} & evidence_present:
        region_label = "спины"
    intro_line = (
        "Вы описали удар/падение и ограничение движения — это в первую очередь травма колена (ушиб, возможно повреждение связок/мениска). Очный осмотр или травматолог при сильной боли, отёке и невозможности опереться — разумный шаг."
        if has_trauma
        else f"Боль в области {region_label} может быть и от перегрузки, но важно вовремя исключить травму."
    )
    hypo_lines = [x for x in (lead_name, second_name) if x]
    q_picked = _pick_first_msk_compatible_question(questions, blob_ortho)
    care_lines = _filter_self_care_msk([str(x) for x in (self_care or [])], blob_ortho)
    return _with_online_sources((
        (interpretation + "\n\n" if interpretation else "")
        + intro_line
        + "\n\n"
        + ("Сейчас в приоритете (варианты для врача, не диагноз):\n" if hypo_lines else "")
        + (_join_lines(hypo_lines) + "\n\n" if hypo_lines else "")
        + "Чтобы точнее оценить серьёзность, уточню:\n"
        + _join_lines([q_picked] if q_picked else [])
        + ("\n\nПока можно:\n" + _join_lines(care_lines[:3]) if care_lines else "")
    ).strip(), payload)

