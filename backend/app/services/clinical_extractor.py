from __future__ import annotations

import re
from typing import Any


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower().replace("ё", "е"))


def _history_text(chat_history: list[Any] | None) -> str:
    parts: list[str] = []
    for row in chat_history or []:
        if isinstance(row, dict):
            role = str(row.get("role") or "").strip().lower()
            if role and role != "user":
                continue
            val = row.get("content") or row.get("text") or ""
            if val:
                parts.append(str(val))
        elif row:
            parts.append(str(row))
    return " ".join(parts).strip()


def _has_any(t: str, needles: tuple[str, ...]) -> bool:
    return any(x in t for x in needles)


def _body_regions_from_scope(scope: str) -> list[str]:
    """Runner-compatible: first element maps via BODY_REGION_TO_BRANCH to expected_branch."""
    if scope in (
        "oral_cavity",
        "respiratory",
        "urinary",
        "gastro",
        "neuro",
        "cardio",
        "allergy_skin",
        "fatigue_deficiency",
        "pleuritic_chest_dyspnea",
        "weight_loss_plateau",
        "women_health",
        "pediatric",
        "ent",
    ):
        return [scope]
    if scope in ("knee", "ankle", "shoulder", "back"):
        return [scope]
    return []


def _detect_primary_scope(present: set[str], t: str) -> str:
    # Явная стоматология / челюсть — до общих эвристик
    explicit_dental = _has_any(
        t,
        ("зуб", "десн", "дёсен", "флюс", "стомат", "зубн", "кариес", "пульпит", "пародонт"),
    )
    respiratory_evidence = {"cough", "sore_throat", "runny_nose", "dyspnea", "sputum"} & present
    # ОРВИ/ЛОР: несколько респираторных маркеров + жар без явной стоматологии — не ветвь «полость рта»
    if len(respiratory_evidence) >= 2 and "fever" in present and not explicit_dental:
        return "respiratory"

    if {"oral_pain", "oral_swelling", "oral_trismus_swallow", "oral_pus", "oral_candidiasis_like", "dry_mouth"} & present:
        return "oral_cavity"

    if {"headache", "photophobia", "neurologic_deficit", "sudden_onset", "dizziness_like"} & present:
        return "neuro"

    if {"burning_urination", "urinary_frequency", "hematuria", "urinary_specific"} & present:
        return "urinary"
    if {"flank_pain", "fever"} <= present:
        return "urinary"

    if "pleuritic_chest_dyspnea" in present:
        return "pleuritic_chest_dyspnea"

    if "weight_loss_plateau" in present:
        return "weight_loss_plateau"

    if {"cough", "sore_throat", "runny_nose", "dyspnea", "sputum"} & present:
        return "respiratory"
    if {"abdominal_pain", "vomiting", "diarrhea", "blood_in_stool"} & present:
        return "gastro"
    if {"fatigue", "anemia_features", "labs_discussed"} & present:
        return "fatigue_deficiency"
    if {"chest_pain", "palpitations", "high_bp_context"} & present:
        return "cardio"
    if {"rash", "itching", "angioedema_risk", "allergy_respiratory_risk"} & present:
        return "allergy_skin"
    if "knee_pain" in present:
        return "knee"
    if "ankle_pain" in present:
        return "ankle"
    if "shoulder_pain" in present:
        return "shoulder"
    if "back_pain" in present:
        return "back"
    return "generic"


def extract_clinical_evidence(user_message: str, chat_history: list[Any] | None = None) -> dict[str, Any]:
    merged = (_history_text(chat_history) + " " + str(user_message or "")).strip()
    t = _norm(merged)

    present: set[str] = set()
    absent: set[str] = set()

    # oral: не использовать голое «рот» — ложные срабатывания на «мокрота» и др.
    # «язык» без уточнения даёт ложные срабатывания («английском языке», «иностранный язык»).
    oral_pain_markers = (
        "зуб",
        "десн",
        "дёсен",
        "щека",
        "стомат",
        "флюс",
        "зуб мудрости",
        "во рту",
        "полости рта",
        "полость рта",
        "изо рта",
        "запах изо рта",
        "болит язык",
        "язык болит",
        "обожгл язык",
        "обожгла язык",
        "налет на языке",
        "налёт на языке",
        "белый язык",
        "язык белый",
    )
    if _has_any(t, oral_pain_markers):
        present.add("oral_pain")
    if _has_any(t, ("отек щеки", "отёк щеки", "отек десны", "отёк десны", "припухла десна")):
        present.add("oral_swelling")
    # «больно глотать» относится к горлу/фарингу, не к стоматологии — не смешивать с тризмом
    if _has_any(t, ("не могу открыть рот", "больно открыть рот", "больно жевать", "тризм")):
        present.add("oral_trismus_swallow")
    if _has_any(t, ("гной", "флюс")):
        present.add("oral_pus")
    if _has_any(t, ("молочниц", "белый налет", "белый налёт", "кандидоз во рту")):
        present.add("oral_candidiasis_like")
    if _has_any(t, ("сухость во рту", "сухо во рту")):
        present.add("dry_mouth")

    # urinary: explicit only; 58: поясница + любой urinary marker -> urinary
    urinary_specific = False
    if _has_any(
        t,
        (
            "жжение при мочеиспускании",
            "больно писать",
            "рези при мочеиспускании",
            "частое мочеиспускание",
            "кровь в моче",
            "почк",
            "пиелонефрит",
            "больно в конце",
            "моч странн",
            "цистит",
        ),
    ):
        urinary_specific = True
        present.add("urinary_specific")

    if _has_any(t, ("жжение при мочеиспускании", "больно писать", "рези при мочеиспускании", "больно в конце", "моч странн", "цистит")):
        present.add("burning_urination")
    if _has_any(t, ("частое мочеиспускание", "часто хожу в туалет", "постоянно в туалет")):
        present.add("urinary_frequency")
    if _has_any(t, ("кровь в моче",)):
        present.add("hematuria")
    if _has_any(t, ("температур", "озноб", "лихорад", "жар")):
        present.add("fever")
    # Не использовать голое «бок»: ложные срабатывания на «глубоко» и др.
    if _has_any(
        t,
        (
            "поясниц",
            "ломит поясницу",
            "почк",
            "боль в боку",
            "болит бок",
            "в боку",
            "с боку",
            "правый бок",
            "левый бок",
        ),
    ):
        if urinary_specific or _has_any(t, ("моч", "рези", "жжение", "писать", "цистит", "почк", "пиелонефрит")):
            present.add("flank_pain")
        else:
            present.add("back_pain")

    # neuro before fatigue
    if _has_any(t, ("головная боль", "болит голова", "мигр")):
        present.add("headache")
    if _has_any(t, ("светобояз", "свет раздражает")):
        present.add("photophobia")
    if _has_any(t, ("онемение", "слабость в руке", "слабость в ноге", "нарушение речи", "нарушение зрения")):
        present.add("neurologic_deficit")
    if _has_any(t, ("внезапно", "резко началось")):
        present.add("sudden_onset")
    if _has_any(t, ("кружит", "шатает", "головокруж", "неприятно стоять")):
        present.add("dizziness_like")

    # fatigue (головокруж не в anemia здесь, чтобы 56 оставался neuro; 62: башка мутная + слабость)
    # «уставший» не содержит подстроку «устал» — явно добавляем уставш*/апатию/неохоту.
    if _has_any(
        t,
        (
            "устал",
            "уставш",
            "устаюсь",
            "устаю",
            "неохот",
            "апат",
            "ничего не хочется",
            "не хочется",
            "слабост",
            "нет сил",
            "башк мутн",
            "башка мутн",
            "мутная голова",
            "голова мутная",
        ),
    ):
        present.add("fatigue")
    if _has_any(t, ("бледн", "одышка", "выпадение волос")):
        present.add("anemia_features")
    if _has_any(t, ("ферритин", "гемоглобин", "витамин d", "b12")):
        present.add("labs_discussed")

    # respiratory
    if _has_any(t, ("каш", "кашель")):
        present.add("cough")
    if _has_any(t, ("мокрот",)):
        present.add("sputum")
    if _has_any(t, ("горл", "больно глотать", "першит")):
        present.add("sore_throat")
    if _has_any(t, ("насморк", "сопл", "заложен нос", "чих")):
        present.add("runny_nose")
    if _has_any(
        t,
        (
            "одыш",
            "не хватает воздуха",
            "воздуха не хватает",
            "нехватки воздуха",
            "тяжело дышать",
            "свистящее дыхание",
            "хрип",
        ),
    ):
        present.add("dyspnea")

    # gastro
    if _has_any(t, ("живот", "болит живот", "в животе")):
        present.add("abdominal_pain")
    if _has_any(t, ("тошн",)):
        present.add("nausea")
    if _has_any(t, ("рвот",)):
        present.add("vomiting")
    if _has_any(t, ("понос", "диаре", "жидкий стул")):
        present.add("diarrhea")
    if _has_any(t, ("черный стул", "чёрный стул", "кровь в стуле")):
        present.add("blood_in_stool")

    # cardio
    if _has_any(t, ("давлен", "давление")):
        present.add("high_bp_context")
    if _has_any(t, ("пульс", "сердцебиение", "перебои", "сердце колотится")):
        present.add("palpitations")
    if _has_any(
        t,
        (
            "боль в груди",
            "болит в груди",
            "болит грудь",
            "болит груд",
            "болью в груди",
            "давит в груди",
            "жмет в груди",
            "жмёт в груди",
        ),
    ):
        present.add("chest_pain")

    deep_breath_worse = _has_any(
        t,
        (
            "глубоко дыш",
            "глубокий вдох",
            "при вдохе",
            "на вдохе",
            "когда дышу",
            "с дыхани",
            "при дыхании",
        ),
    )
    if "chest_pain" in present and "dyspnea" in present and deep_breath_worse:
        present.add("pleuritic_chest_dyspnea")

    wl_direct = _has_any(
        t,
        (
            "не могу сбросить вес",
            "не сбрасывается вес",
            "вес не уходит",
            "вес не снижается",
            "вес стоит",
            "не худею",
            "не худеет",
            "не удается похудеть",
            "не удаётся похудеть",
            "лишний вес",
            "набор веса",
            "избыток веса",
        ),
    )
    if not wl_direct and re.search(r"(?<![а-яё0-9])вес(?![а-яё0-9])", t):
        wl_direct = _has_any(
            t,
            (
                "уже год",
                "уже полгода",
                "целый год",
                "больше года",
                "несколько лет",
                "полгода",
                "6 месяцев",
                "пол года",
                "месяцев",
                "пробовал всё",
                "пробовал все",
                "все пробовал",
                "всё пробовал",
                "ничего не помогает",
            ),
        )
    if wl_direct:
        present.add("weight_loss_plateau")

    # allergy / skin
    if _has_any(t, ("сып", "пятн", "волдыр", "крапив")):
        present.add("rash")
    if _has_any(t, ("зуд", "чешется")):
        present.add("itching")
    if _has_any(t, ("отек губ", "отёк губ", "отек языка", "отёк языка")):
        present.add("angioedema_risk")
    if _has_any(t, ("одыш", "свистящее дыхание", "не хватает воздуха", "воздуха не хватает", "нехватки воздуха")) and (
        "rash" in present or "itching" in present
    ):
        present.add("allergy_respiratory_risk")

    # orthopedics
    if "колен" in t:
        present.add("knee_pain")
    if _has_any(t, ("голеностоп", "лодыж", "щиколот", "стоп")):
        present.add("ankle_pain")
    if _has_any(t, ("подвернул", "скрутил стопу", "неловко наступил", "подворачив")):
        present.add("twisting_motion")
    if _has_any(t, ("плеч", "плечо")):
        present.add("shoulder_pain")
    if _has_any(t, ("больно поднимать руку", "боль при отведении", "не могу поднять руку")):
        present.add("pain_on_abduction")
    if _has_any(t, ("болит спина", "боль в спине", "прострел", "шея болит")):
        present.add("back_pain")
    if _has_any(t, ("отдает в ногу", "отдаёт в ногу", "по ноге тянет", "прострел в ногу")):
        present.add("radicular_pain")
        present.add("back_pain")
    if _has_any(t, ("отек", "отёк", "опух", "припух")):
        present.add("swelling")
    if _has_any(t, ("не могу наступить", "невозможно наступить", "не опираюсь")):
        present.add("cannot_bear_weight")
    if _has_any(t, ("деформац", "криво стоит")):
        present.add("gross_deformity")
    if _has_any(t, ("горячий сустав", "горячее колено")) and "fever" in present:
        present.add("hot_swollen_joint_with_fever")

    primary_scope = _detect_primary_scope(present, t)

    return {
        "chief_complaint": str(user_message or "").strip(),
        "primary_scope": primary_scope,
        "body_regions": _body_regions_from_scope(primary_scope),
        "evidence_present": sorted(present),
        "evidence_absent": sorted(absent),
        "evidence_unknown": [],
    }
