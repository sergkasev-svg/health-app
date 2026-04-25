from __future__ import annotations

from typing import Any

from app.services.quality_autolearn import detect_topics, get_conflicting_topics, topic_keywords


_INJURY_CONTEXT_MARKERS = (
    "порез",
    "рана",
    "травм",
    "палец",
    "пальц",
    "нога",
    "ступн",
    "стоп",
    "рука",
    "колен",
    "голен",
    "плеч",
    "локт",
    "запяст",
    "спин",
    "поясниц",
    "шея",
    "голов",
    "глаз",
    "ушиб",
    "растяж",
    "вывих",
    "перелом",
    "ожог",
)
_KNEE_LEG_MARKERS = (
    "колен",
    "нога",
    "голен",
    "ступн",
    "стоп",
)
_FALL_MARKERS = ("упал", "упала", "паден", "подвернул", "подвернула")
_HEAD_INJURY_MARKERS = ("голов", "затыл", "висок", "череп", "сотряс")
_EYE_INJURY_MARKERS = ("глаз", "веко", "роговиц")
_HAND_FINGER_MARKERS = ("палец", "пальц", "кисть", "ладон", "запяст", "рука")
_SHOULDER_ARM_MARKERS = ("плеч", "предплеч", "локт", "рука")
_ANKLE_FOOT_MARKERS = ("голеностоп", "лодыж", "стоп", "ступн")
_BACK_NECK_MARKERS = ("спин", "поясниц", "шея")
_BURN_MARKERS = ("ожог", "обжег", "обжёг", "кипят", "паром")
_ANORECTAL_MARKERS = (
    "гемор",
    "стул",
    "прокт",
    "прямая киш",
    "задний проход",
)
_FOOD_OVERLOAD_MARKERS = (
    "семеч",
    "переел",
    "переела",
    "переед",
    "жирн",
    "жарен",
    "пища",
    "еда",
    "поел",
    "съел",
)
_HISTAMINE_FOOD_MARKERS = (
    "сыр",
    "творог",
    "кефир",
    "йогурт",
    "фермент",
    "выдержан",
    "вино",
)
_NEURO_GI_MARKERS = (
    "голов",
    "тошн",
    "мутит",
)
_CARDIO_AUTONOMIC_MARKERS = (
    "давлен",
    "пульс",
    "щитовид",
    "аритм",
    "карди",
)


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _contains_any(text: str, keys: tuple[str, ...]) -> bool:
    t = _norm(text)
    return any(k in t for k in keys)


def _mismatch_reason(user_message: str, answer: str) -> str:
    q = _norm(user_message)
    a = _norm(answer)
    if not q or not a:
        return "empty"
    if _contains_any(q, _INJURY_CONTEXT_MARKERS) and _contains_any(a, _ANORECTAL_MARKERS):
        return "injury_vs_anorectal"
    if _contains_any(q, _ANORECTAL_MARKERS) and _contains_any(a, _INJURY_CONTEXT_MARKERS):
        return "anorectal_vs_injury"
    if (
        _contains_any(q, _FOOD_OVERLOAD_MARKERS)
        and _contains_any(q, _NEURO_GI_MARKERS)
        and _contains_any(a, _CARDIO_AUTONOMIC_MARKERS)
        and not _contains_any(a, _FOOD_OVERLOAD_MARKERS)
    ):
        return "food_vs_pressure"

    q_topics = detect_topics(q)
    a_topics = detect_topics(a)
    if q_topics and a_topics and not (q_topics & a_topics):
        return "topic_mismatch"

    conflicting = get_conflicting_topics(q_topics, min_hits=2) if q_topics else set()
    if conflicting and a_topics and (a_topics & conflicting):
        return "known_collision"
    return ""


def _injury_safe_answer(user_message: str) -> str:
    q = _norm(user_message)
    has_knee_leg = _contains_any(q, _KNEE_LEG_MARKERS)
    has_fall = _contains_any(q, _FALL_MARKERS)
    has_head = _contains_any(q, _HEAD_INJURY_MARKERS)
    has_eye = _contains_any(q, _EYE_INJURY_MARKERS)
    has_hand_finger = _contains_any(q, _HAND_FINGER_MARKERS)
    has_shoulder_arm = _contains_any(q, _SHOULDER_ARM_MARKERS)
    has_ankle_foot = _contains_any(q, _ANKLE_FOOT_MARKERS)
    has_back_neck = _contains_any(q, _BACK_NECK_MARKERS)
    has_burn = _contains_any(q, _BURN_MARKERS)

    if has_burn:
        return (
            "Похоже на ожог. Сразу охладите место ожога прохладной водой 15–20 минут (без льда), "
            "снимите кольца/тесные вещи рядом и закройте чистой сухой повязкой. "
            "Не вскрывайте пузыри и не мажьте маслом/спиртом. "
            "Срочно в травмпункт/103, если ожог глубокий, на лице/кисти/гениталиях, большой площади, "
            "есть сильная боль, слабость или признаки инфекции."
        )

    if has_head and has_fall:
        return (
            "Похоже на травму головы после падения. Сейчас нужен щадящий режим, холод через ткань 10–15 минут "
            "и наблюдение за состоянием. "
            "Проверьте, нет ли нарастающей головной боли, тошноты/рвоты, сонливости, спутанности, "
            "ухудшения зрения или потери сознания. "
            "Если есть любой из этих признаков — срочно 103. "
            "Даже без красных флагов лучше очно обратиться сегодня в травмпункт."
        )

    if has_eye:
        return (
            "Похоже на травму глаза. Не трите глаз и не давите на него, снимите контактную линзу, если она есть. "
            "Промойте чистой водой только при поверхностном загрязнении, затем закройте глаз стерильной салфеткой. "
            "Срочно в травмпункт/офтальмологию сегодня, а при резкой боли, падении зрения, крови в глазу "
            "или химическом воздействии — сразу 103."
        )

    if has_hand_finger and ("порез" in q or "рана" in q or "кров" in q):
        return (
            "Похоже на травму с кровью (кисть/палец). Прижмите рану чистой салфеткой 10–15 минут, "
            "поднимите руку выше уровня сердца, обработайте края антисептиком и наложите повязку. "
            "Проверьте движение и чувствительность пальцев. "
            "Если кровь не останавливается 15–20 минут, рана глубокая, нарушено движение/чувствительность "
            "или есть инородное тело — срочно в травмпункт/103."
        )

    if has_shoulder_arm and has_fall:
        return (
            "Похоже на травму плеча/руки после падения. Зафиксируйте руку в удобном положении (косынка), "
            "приложите холод через ткань 10–15 минут и ограничьте нагрузку. "
            "Если выраженная деформация, резкая боль, хруст, нарастающий отек или невозможно поднять/согнуть руку — "
            "сегодня в травмпункт, при сильном ухудшении 103."
        )

    if has_ankle_foot and has_fall:
        return (
            "Похоже на травму голеностопа/стопы. Действуйте по RICE: покой, холод 10–15 минут, "
            "эластичная фиксация, держите ногу выше уровня сердца. "
            "Проверьте, можете ли наступать хотя бы 4 шага. "
            "Если наступать трудно/невозможно, быстро растет отек, есть сильная боль в костных точках "
            "или выраженный синяк — сегодня в травмпункт."
        )

    if has_back_neck and has_fall:
        return (
            "Похоже на травму спины/шеи после падения. Ограничьте движения, избегайте резких поворотов, "
            "можно холод через ткань 10–15 минут. "
            "Если есть онемение, слабость в руках/ногах, боль с прострелом, нарушение мочеиспускания "
            "или усиливающаяся боль — срочно в травмпункт/103."
        )

    if has_knee_leg and has_fall:
        return (
            "Похоже на травму колена с ссадиной/кровью после падения. Действуйте по шагам: "
            "прижмите ссадину чистой салфеткой 10–15 минут, промойте водой, обработайте края антисептиком и наложите повязку. "
            "Для колена: приложите холод через ткань на 10–15 минут, держите ногу в покое и приподнятой. "
            "Проверьте сейчас, сгибается ли колено и можете ли наступать без резкой боли. "
            "Если трудно наступать, колено не сгибается/заклинивает, быстро нарастает отек, есть выраженная боль, "
            "подозрение на глубокую рану или кровотечение не останавливается 15–20 минут — сегодня в травмпункт, при резком ухудшении 103."
        )
    return (
        "Похоже на травму с кровью. Действуйте по шагам: "
        "прижмите рану чистой салфеткой 10–15 минут, поднимите конечность выше сердца, "
        "обработайте края антисептиком и наложите стерильную повязку. "
        "Срочно в травмпункт/103, если кровь не останавливается 15–20 минут, рана глубокая "
        "или есть онемение/нарушение движения."
    )


def _generic_focus_answer(user_message: str) -> str:
    kw_map = {
        "кашл": "кашель",
        "горл": "горло",
        "голов": "голова",
        "температур": "температура",
        "давлен": "давление",
    }
    topics = detect_topics(user_message or "")
    if topics:
        top = next(iter(topics))
        kws = topic_keywords(top)
        kw = kws[0] if kws else "симптом"
        kw = kw_map.get(kw, kw)
        return f"Как давно беспокоит {kw}?"
    return "Как давно это беспокоит?"


def _food_overload_safe_answer() -> str:
    return (
        "Похоже на реакцию после переедания жирной/жареной пищи (в т.ч. семечек): "
        "часто бывает тошнота, тяжесть и головная боль. Что делать сейчас: "
        "1) покой и вода маленькими глотками, "
        "2) пауза в еде 3–4 часа, затем легкая пища, "
        "3) без алкоголя, кофе и жирного до завтра. "
        "Срочно 103/неотложка, если нарастает сильная рвота, резкая боль в животе, "
        "высокая температура, многократная рвота или выраженная слабость/обморок."
    )


def _food_histamine_followups() -> list[str]:
    return [
        "Через сколько минут/часов после еды начинается головная боль или тошнота?",
        "Повторяется ли реакция именно на сыр/творог/ферментированные продукты?",
        "Есть ли вместе с симптомами покраснение, зуд, заложенность носа, сердцебиение?",
        "Становится ли легче при исключении триггеров на 10-14 дней?",
        "Были ли похожие эпизоды после алкоголя, шоколада или копченостей?",
    ]


def _food_histamine_safe_answer(user_message: str) -> tuple[str, list[str]]:
    conditions: list[str] = []
    followups: list[str] = _food_histamine_followups()
    try:
        # Reuse existing food/histamine knowledge layer instead of hardcoding.
        from app.services.food_triggers_lookup import build_food_trigger_context

        ctx = build_food_trigger_context(user_message or "")
        if isinstance(ctx, dict):
            conditions = [str(x).strip() for x in (ctx.get("possible_conditions") or []) if str(x).strip()]
            followups.extend([str(x).strip() for x in (ctx.get("followup_questions") or []) if str(x).strip()])
    except Exception:
        pass

    low_conditions = [c.lower() for c in conditions]
    has_histamine_signal = any(("гистамин" in c) or ("mcas" in c) or ("биоген" in c) for c in low_conditions)
    hypothesis_line = (
        "Похоже на пищевой триггер с чувствительностью к гистамину/биогенным аминам; "
        "MCAS-подобная гиперреактивность — как дифференциальная гипотеза."
        if has_histamine_signal
        else "Похоже на пищевой триггер; среди гипотез — чувствительность к гистамину/биогенным аминам."
    )
    text = (
        f"{hypothesis_line}\n"
        "Что делать сейчас: покой, вода маленькими глотками, пауза в еде 3-4 часа, "
        "далее щадящий прием пищи; избегать сегодня триггеров (сыр, творог, ферментированные и жареные продукты).\n"
        "Кого подключить планово: аллерголог-иммунолог и/или гастроэнтеролог, при частых головных болях — невролог.\n"
        "Что обсудить по анализам с врачом: ОАК с эозинофилами, общий IgE (как фон), "
        "базальная триптаза (при подозрении на MCAS), пищевой дневник с триггерами 2-3 недели. "
        "Для маршрутизации в приложении используйте профиль «Гистамин/MCAS-check».\n"
        "Срочно 103/неотложка при нарастающей сильной головной боли, многократной рвоте, "
        "затрудненном дыхании, отеке губ/языка, выраженной слабости или обмороке."
    )
    dedup: list[str] = []
    seen: set[str] = set()
    for q in followups:
        s = str(q or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(s)
    return text, dedup[:6]


def apply_final_relevance_gate(user_message: str, payload: dict[str, Any], channel: str = "chat") -> dict[str, Any]:
    out = dict(payload or {})
    response = str(out.get("response") or "").strip()
    source = str(out.get("response_source") or "").strip().lower()
    # Respect deterministic safety/triage guards from upstream router.
    passthrough_sources = {
        "food_symptom_super_guard",
        "food_overload_guard",
        "upper_abdominal_guard",
        "postmeal_bloating_guard",
        "postmeal_systemic_guard",
        "acute_injury_guard",
        "anorectal_bleeding_guard",
        "headache_autonomic_guard",
        "nosebleed_guard",
    }
    if source in passthrough_sources:
        out["relevance_gate"] = {"applied": True, "blocked": False, "reason": "passthrough_source"}
        return out
    reason = _mismatch_reason(user_message, response)
    if not reason:
        out["relevance_gate"] = {"applied": True, "blocked": False, "reason": ""}
        return out

    q = _norm(user_message)
    has_blood = "кров" in q
    has_injury_context = _contains_any(q, _INJURY_CONTEXT_MARKERS)
    if reason == "food_vs_pressure":
        q = _norm(user_message)
        has_hist_food = _contains_any(q, _HISTAMINE_FOOD_MARKERS)
        # Recurrent food-related headaches/nausea should surface histamine/amine differential,
        # not only generic "overeating" advice.
        if has_hist_food and _contains_any(q, _NEURO_GI_MARKERS):
            fixed, followups = _food_histamine_safe_answer(user_message)
        else:
            fixed = _food_overload_safe_answer()
            followups = _food_histamine_followups()
        out["response_source"] = "final_relevance_gate_food"
    elif has_injury_context and has_blood:
        fixed = _injury_safe_answer(user_message)
        followups = []
        severity = str(out.get("severity") or "").upper()
        if severity not in {"YELLOW", "RED"}:
            out["severity"] = "YELLOW"
        out["response_source"] = "final_relevance_gate_injury"
    else:
        fixed = _generic_focus_answer(user_message)
        followups = []
        out["response_source"] = "final_relevance_gate_reask"

    out["response"] = fixed
    out["response_simple"] = fixed[:6000] if len(fixed) > 6000 else fixed
    structured = out.get("structured")
    if not isinstance(structured, dict):
        structured = {}
    sq = structured.get("suggested_questions")
    if not isinstance(sq, list):
        sq = []
    sq_out: list[str] = []
    seen_sq: set[str] = set()
    for q_item in list(sq) + list(followups):
        s = str(q_item or "").strip()
        if not s:
            continue
        lk = s.lower()
        if lk in seen_sq:
            continue
        seen_sq.add(lk)
        sq_out.append(s)
    structured["suggested_questions"] = sq_out[:6]
    out["structured"] = structured
    out["relevance_gate"] = {"applied": True, "blocked": True, "reason": reason, "channel": channel}
    return out


def apply_analysis_relevance_gate(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """
    Relevance gate for uploaded lab analysis flow (/api/ai/analyze):
    - validates narrative `text` against source payload context
    - prunes hypothesis labels that collide with the detected source topic
    """
    src = dict(payload or {})
    out = dict(result or {})

    raw_text = str(src.get("raw_text") or "").strip()
    symptoms = str(src.get("symptoms_text") or src.get("symptoms") or "").strip()
    markers = src.get("lab_markers") or {}
    marker_hint = " ".join([str(k) for k in markers.keys()]) if isinstance(markers, dict) else ""
    report_type = str(out.get("report_type") or "").strip()
    user_message = " ".join([x for x in (raw_text, symptoms, marker_hint, report_type) if x]).strip()
    if not user_message:
        user_message = "анализы и лабораторный отчёт"

    probe = {
        "response": str(out.get("text") or ""),
        "response_source": str(out.get("response_source") or "analysis"),
        "severity": str(out.get("severity") or ""),
        "structured": {},
    }
    gated = apply_final_relevance_gate(user_message, probe, channel="analysis")
    out["text"] = str(gated.get("response") or out.get("text") or "")
    rg = dict(gated.get("relevance_gate") or {})
    if "applied" not in rg:
        rg["applied"] = True
    if "blocked" not in rg:
        rg["blocked"] = False
    if "reason" not in rg:
        rg["reason"] = ""
    rg["channel"] = "analysis"
    out["relevance_gate"] = rg
    out["response_source"] = str(gated.get("response_source") or out.get("response_source") or "analysis")

    # Optional hypothesis pruning by topic compatibility.
    q_topics = detect_topics(user_message)
    if q_topics and isinstance(out.get("hypotheses"), list):
        cleaned: list[Any] = []
        conflicting = get_conflicting_topics(q_topics, min_hits=2)
        for h in out.get("hypotheses") or []:
            label = str((h or {}).get("label") if isinstance(h, dict) else h or "")
            a_topics = detect_topics(label)
            if a_topics and not (a_topics & q_topics):
                if conflicting and (a_topics & conflicting):
                    continue
            cleaned.append(h)
        if cleaned:
            out["hypotheses"] = cleaned
    return out

