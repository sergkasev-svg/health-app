"""
Анализ текста документа (анализы, выписки): запрос к базам знаний, выводы, рекомендации.
"""
import re
from typing import Any

from app.services.clinical_profiles import search_clinical_profiles
from app.services.knowledge_base import search_scenarios
from app.services.offline_search import search_offline_with_formats


_GENERIC_TOKENS = {
    "дата",
    "пациент",
    "анализ",
    "результат",
    "норма",
    "нормальный",
    "уровень",
    "маркер",
    "маркеры",
    "метод",
    "биоматериал",
    "креатинина",
    "ммоль",
    "моль",
    "кислота",
    "кислоты",
    "документ",
    "страница",
}
_DOMAIN_RULES = {
    "metabolic": ("метабол", "митохонд", "кребс", "органическ", "аминокислот", "витамин", "коэнзим", "карнитин", "дисбиоз"),
    "respiratory": ("кашл", "одыш", "бронх", "горл", "тонзилл", "фаринг", "насморк", "хрип", "орви"),
    "gi": ("жкт", "живот", "кишеч", "изжог", "метеор", "диаре", "запор", "тошнот", "рвот"),
    "cardio": ("серд", "давлен", "тахик", "аритм", "кардио", "холест"),
    "endo": ("диаб", "глюкоз", "ттг", "щитовид", "гормон", "инсулин"),
}
_ACUTE_CLINICAL_DRIFT_KEYS = (
    "орви",
    "бронхит",
    "тонзиллит",
    "фарингит",
    "ангина",
    "пневмони",
    "цистит",
    "пиелонефрит",
)
_SYMPTOM_SIGNAL_KEYS = ("боль", "болит", "кашель", "одышка", "температура", "горло", "насморк", "жалобы", "симптомы")


def _tokens(text: str) -> set[str]:
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", (text or "").lower())
    out: set[str] = set()
    for w in s.split():
        if len(w) < 4:
            continue
        if w in _GENERIC_TOKENS:
            continue
        out.add(w)
    return out


def _infer_domains(text: str) -> set[str]:
    low = (text or "").lower()
    out: set[str] = set()
    for domain, hints in _DOMAIN_RULES.items():
        if any(h in low for h in hints):
            out.add(domain)
    if not out:
        out.add("general")
    return out


def _has_symptom_signal(text: str) -> bool:
    s = re.sub(r"[^\w\sа-яёa-z0-9]", " ", (text or "").lower())
    toks = {w for w in s.split() if len(w) >= 3}
    return bool(set(_SYMPTOM_SIGNAL_KEYS).intersection(toks))


def _candidate_relevant(query_text: str, candidate_text: str) -> bool:
    q_domains = _infer_domains(query_text)
    c_domains = _infer_domains(candidate_text)
    q_tokens = _tokens(query_text)
    c_tokens = _tokens(candidate_text)
    overlap = len(q_tokens.intersection(c_tokens))
    q_low = (query_text or "").lower()
    c_low = (candidate_text or "").lower()
    has_symptom_signal = _has_symptom_signal(query_text)

    # Hard guard: metabolic lab docs should not drift into respiratory cluster
    # without explicit respiratory signal in the document itself.
    if "metabolic" in q_domains and "respiratory" in c_domains and "respiratory" not in q_domains:
        return False

    # For lab/metabolic documents require stronger evidence before pulling
    # unrelated clinical narratives (prevents "mix everything together").
    if "metabolic" in q_domains and "metabolic" not in c_domains:
        if overlap < 4:
            return False
        if not has_symptom_signal and any(k in c_low for k in _ACUTE_CLINICAL_DRIFT_KEYS):
            return False

    if "general" not in q_domains and "general" not in c_domains and not (q_domains & c_domains):
        return False
    return overlap >= 2 or bool(q_domains & c_domains)


def _fetch_modern_evidence(scenarios: list[dict]) -> tuple[list[str], list[str]]:
    """Собирает блоки «актуальные данные» из сценариев (заметки и ссылки из базы)."""
    modern_evidence: list[str] = []
    evidence_links: list[str] = []
    seen_links: set[str] = set()

    for sc in scenarios:
        for note in sc.get("evidence_notes") or []:
            if note and note.strip() and note.strip() not in modern_evidence:
                modern_evidence.append(note.strip())
        for link in sc.get("evidence_links") or []:
            if link and link.strip() and link.strip() not in seen_links:
                seen_links.add(link.strip())
                evidence_links.append(link.strip())

    return modern_evidence, evidence_links


def _to_float(raw: str) -> float | None:
    s = str(raw or "").strip().replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _has_direct_vitamin_d_evidence(text: str) -> bool:
    """
    Accept vitamin D conclusions only when the document directly contains
    measurement context (25(OH)D / 25-OH / calcidiol style marker + number).
    """
    low = (text or "").lower()
    if not low.strip():
        return False
    vitd_marker = (
        "25(oh)d" in low
        or "25-oh" in low
        or "25 oh" in low
        or "кальцидиол" in low
        or "витамин d" in low
        or "витамина d" in low
    )
    if not vitd_marker:
        return False
    has_num = bool(re.search(r"\d+[.,]?\d*", low))
    has_unit = any(u in low for u in ("нг/мл", "nmol", "нмоль/л", "pg/ml", "мкг/л"))
    return has_num and (has_unit or "25(oh)d" in low or "25-oh" in low or "кальцидиол" in low)


def _clean_marker_name(line: str) -> str:
    s = re.sub(r"\s+", " ", str(line or "")).strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("("):
        return ""
    if ")" in s and "(" not in s:
        # Continuation alias line like "октандиовая кислота)".
        return ""
    if low.startswith("в т.ч."):
        return ""
    # Keep canonical marker name before aliases in brackets.
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    s = re.sub(r"\b(ммоль/моль|ммоль/л|отн\.ед\./моль)\b.*$", "", s, flags=re.I).strip()
    s = s.rstrip(":;,. ").strip()
    if not s:
        return ""
    generic = {"кислота", "кислоты"}
    if s.lower() in generic:
        return ""
    return s


def _extract_lab_deviations(text: str) -> list[str]:
    """
    Извлекает из текста лабораторного бланка строки с отклонениями от нормы
    (колонки «Отклонение» / «Критичность»: «выше нормы», «ниже нормы»).
    Возвращает короткие формулировки для блока «Отклонения от нормы» в отчёте.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln and ln.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        low = line.lower()
        if "отклонение от нормы" not in low and "выше нормы" not in low and "ниже нормы" not in low:
            continue
        direction = "выше нормы" if "выше нормы" in low else "ниже нормы" if "ниже нормы" in low else None
        if not direction:
            direction = "отклонение от нормы"
        # Ищем назад: название показателя, затем числа (результат, норма)
        test_name = ""
        result_val = None
        norm_str = ""
        numeric_lines: list[list[float]] = []
        for j in range(i - 1, max(i - 10, -1), -1):
            prev = lines[j]
            low_prev = prev.lower()
            if "результат" in low_prev or "норма" in low_prev or "отклонение" in low_prev or "критичность" in low_prev:
                continue
            nums = re.findall(r"-?\d+[.,]?\d*", prev)
            floats = []
            for n in nums:
                f = _to_float(n)
                if f is not None and 0 <= f < 1000:
                    floats.append(f)
            if floats:
                numeric_lines.append(floats)
            if re.search(r"[а-яёА-ЯЁ]", prev) and len(prev) > 12 and not test_name:
                candidate = re.sub(r"\s+", " ", prev).strip()
                if len(candidate) < 150:
                    test_name = candidate
        if not test_name:
            continue
        if numeric_lines:
            first_line = numeric_lines[0]
            if first_line:
                result_val = first_line[0]
            if len(numeric_lines) >= 2 and numeric_lines[1]:
                refs = numeric_lines[1]
                if len(refs) >= 2:
                    norm_str = f"{refs[0]:.2f}–{refs[1]:.2f}".replace(".", ",")
                else:
                    norm_str = ("<" if "ниже" in direction else ">") + f"{refs[0]:.2f}".replace(".", ",")
            elif first_line and len(first_line) >= 2:
                norm_str = f"{first_line[1]:.2f}".replace(".", ",")
        key = (test_name[:60] + " " + direction).strip()
        if key in seen:
            continue
        seen.add(key)
        part = f"{test_name}: "
        if result_val is not None:
            part += f"{result_val} "
        if norm_str:
            part += f"(норма {norm_str}) "
        part += "— " + direction
        out.append(part.strip())
    return out


def _extract_numeric_markers(text: str) -> list[dict[str, Any]]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln and ln.strip()]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        low = line.lower()
        if "кислот" not in low:
            continue
        if low.startswith("маркеры ") or low.startswith("результатов ") or low.startswith("обязательна "):
            continue
        name = _clean_marker_name(line)
        if not name or len(name) < 6:
            continue
        nums: list[float] = []
        end_idx = i
        for j in range(i, min(i + 16, len(lines))):
            line_j = lines[j]
            # Ignore chemistry naming lines like "2,3-пиридин..." to avoid false numeric capture.
            has_letters = bool(re.search(r"[A-Za-zА-Яа-яЁё]", line_j))
            if has_letters:
                # Allow compact rows where letters are only units.
                compact = re.sub(r"(ммоль/моль|ммоль/л|креатинина|отн\.ед\./моль)", "", line_j, flags=re.I).strip()
                if re.search(r"[A-Za-zА-Яа-яЁё]", compact):
                    continue
            vals = re.findall(r"-?\d+[.,]?\d*", line_j)
            for v in vals:
                f = _to_float(v)
                if f is not None:
                    nums.append(f)
            end_idx = j
            if len(nums) >= 3:
                break
        if len(nums) < 3:
            continue
        ref_low, ref_high, value = nums[0], nums[1], nums[2]
        if ref_high <= ref_low:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        ratio = (value - ref_low) / (ref_high - ref_low)
        status = "normal"
        if value > ref_high:
            status = "high"
        elif value < ref_low:
            status = "low"
        elif ratio >= 0.85:
            status = "near_high"
        comment = ""
        for j in range(end_idx, min(end_idx + 8, len(lines))):
            if lines[j].lower().startswith("в т.ч."):
                comment = lines[j]
                break
        out.append(
            {
                "name": name,
                "ref_low": ref_low,
                "ref_high": ref_high,
                "value": value,
                "ratio": ratio,
                "status": status,
                "comment": comment,
            }
        )
    return out


def _interpret_marker(marker: dict[str, Any]) -> dict[str, list[str]]:
    name = str(marker.get("name") or "")
    low = name.lower()
    value = float(marker.get("value") or 0.0)
    ref_low = float(marker.get("ref_low") or 0.0)
    ref_high = float(marker.get("ref_high") or 0.0)
    status = str(marker.get("status") or "normal")
    comment = str(marker.get("comment") or "").strip()

    finding = f"{name}: {value:.3f} (референс {ref_low:.3f}-{ref_high:.3f})"
    finding += " — выше нормы." if status == "high" else " — ближе к верхней границе." if status == "near_high" else ""
    out = {"findings": [], "hypotheses": [], "recommendations": [], "diagnostics": []}
    if status not in ("high", "near_high"):
        return out
    out["findings"].append(finding)
    # Safety normalization for known OCR-derived mislabels in source comments.
    if "формиминоглутамин" in low:
        comment_low = comment.lower()
        if any(k in comment_low for k in ("глицин", "в5", "b5")):
            comment = "В т.ч. маркер фолатного обмена (FIGLU); при повышении требует оценки статуса фолатов (B9) и витамина B12."
    if comment:
        out["hypotheses"].append(f"{name}: {comment}")

    if "миндаль" in low:
        out["hypotheses"].append("Гипотеза: повышенная миндальная кислота может отражать контакт с производными бензола/стирола.")
        out["recommendations"].append("Минимизировать контакт с растворителями/лакокрасочными материалами, улучшить вентиляцию помещения.")
        out["diagnostics"].append("Контроль маркеров интоксикации производными бензола в динамике (повтор через 4-8 недель).")
    elif "квинолин" in low:
        out["hypotheses"].append("Гипотеза: активация пути триптофана/кинуренина и воспалительного ответа.")
        out["recommendations"].append("Оценить противовоспалительный режим: сон, контроль стресса, питание с достаточным белком и омега-3.")
        out["diagnostics"].append("ОАК с лейкоформулой, СРБ/СОЭ, при показаниях консультация педиатра/инфекциониста.")
    elif "пиколин" in low:
        out["hypotheses"].append("Гипотеза: активация Т-клеточного иммунного ответа.")
        out["recommendations"].append("План наблюдения у врача с оценкой клинического контекста и симптомов воспаления.")
        out["diagnostics"].append("Контроль воспалительных маркеров и динамики триптофанового профиля.")
    elif "бензойн" in low:
        out["hypotheses"].append("Гипотеза: бактериальный дисбиоз кишечника и возможный дефицит глицина/витамина B5.")
        out["recommendations"].append("Питание с достаточным белком, клетчаткой и ограничением избытка простых сахаров; обсудить коррекцию B5/глицина.")
        out["diagnostics"].append("Оценка кишечного профиля/кала по показаниям, повтор органических кислот в динамике.")
    elif "ксантурен" in low:
        out["hypotheses"].append("Гипотеза: пограничная нагрузка по пути триптофана, возможна относительная недостаточность B6.")
        out["recommendations"].append("Контроль достаточности B6 с коррекцией рациона и повторным анализом в динамике.")
        out["diagnostics"].append("Проверка B6-ассоциированных маркеров при повторном исследовании.")
    elif "формиминоглутамин" in low:
        out["hypotheses"].append("Гипотеза: повышение FIGLU может отражать нарушение фолатного цикла и/или дефицит фолатов (B9) и витамина B12.")
        out["recommendations"].append("Питание с достаточным поступлением фолатов и B12; коррекцию доз проводить только с врачом.")
        out["diagnostics"].append("Оценить фолаты (B9), витамин B12 и при показаниях метилмалоновую кислоту в динамике.")
    else:
        out["hypotheses"].append("Гипотеза: метаболическое отклонение требует клинической верификации в контексте симптомов.")
        out["recommendations"].append("Повторный контроль показателя и очная интерпретация врачом.")
        out["diagnostics"].append("План дообследования по профилю отклонения.")
    return out


def analyze_document_text(text: str) -> dict[str, Any]:
    """
    Анализирует извлечённый текст документа: офлайн-справочники + база сценариев.
    Возвращает структурированные выводы и рекомендации для отчёта.
    """
    text = (text or "").strip()
    if not text:
        return _empty_analysis()

    # Поиск по офлайн-базам (лекарства, первая помощь, симптомы)
    offline = search_offline_with_formats(text, max_med=5, max_guide=5)
    professional_offline = offline.get("professional") or ""
    simple_offline = offline.get("simple") or ""

    # Релевантные сценарии из базы знаний (дефицит железа, кортизол, сон, липиды и т.д.)
    scenarios = search_scenarios(text, top_k=5)
    profiles = search_clinical_profiles(text, top_k=5)

    conclusions = []
    diagnosis_hints = []
    treatment = []
    nutrition = []
    activity = []
    prevention = []
    severity = "GREEN"
    marker_findings: list[str] = []
    marker_hypotheses: list[str] = []
    marker_recommendations: list[str] = []
    marker_diagnostics: list[str] = []

    for sc in scenarios:
        scenario_blob = " ".join(
            [
                str(sc.get("name") or ""),
                str(sc.get("context") or ""),
                " ".join(sc.get("symptoms") or []),
                " ".join(sc.get("recommendations") or []),
            ]
        )
        if not _candidate_relevant(text, scenario_blob):
            continue
        name = sc.get("name") or ""
        sev = (sc.get("severity") or "GREEN").upper()
        if sev == "RED":
            severity = "RED"
        elif sev == "YELLOW" and severity != "RED":
            severity = "YELLOW"
        conclusions.append(name)
        ctx = sc.get("context") or ""
        if ctx:
            diagnosis_hints.append(f"{name}: {ctx}")
        for key, out_list in (
            ("treatment", treatment),
            ("nutrition", nutrition),
            ("activity", activity),
            ("prevention", prevention),
        ):
            items = sc.get(key)
            if items and isinstance(items, list):
                for s in items:
                    if s and s.strip() and s.strip() not in out_list:
                        out_list.append(s.strip())
        recs = sc.get("recommendations") or []
        if not sc.get("treatment") and recs:
            for r in recs:
                if r and r.strip() and r.strip() not in treatment:
                    treatment.append(r.strip())

    # Дополнение клиническими профилями 350+ (оффлайн-каталог)
    for p in profiles:
        profile_blob = " ".join(
            [
                str(p.get("name") or ""),
                str(p.get("category") or ""),
                str(p.get("description") or ""),
                " ".join(p.get("diagnostics") or []),
                " ".join(p.get("treatment") or []),
            ]
        )
        if not _candidate_relevant(text, profile_blob):
            continue
        p_name = str(p.get("name") or "").strip()
        p_icd = str(p.get("icd10") or "").strip()
        if p_name and p_name not in conclusions:
            conclusions.append(p_name)
        if p_name:
            hint = p_name + (f" [{p_icd}]" if p_icd else "")
            if hint not in diagnosis_hints:
                diagnosis_hints.append(hint)
        for d in (p.get("diagnostics") or [])[:3]:
            line = f"Диагностика ({p_name}): {d}"
            if line not in diagnosis_hints:
                diagnosis_hints.append(line)
        for t in (p.get("treatment") or [])[:3]:
            if t not in treatment:
                treatment.append(t)
        meds = [m for m in (p.get("medications_recommended") or []) if m]
        if meds:
            med_line = "Рекомендуемые препараты (обсудить с врачом): " + ", ".join(meds[:5])
            if med_line not in treatment:
                treatment.append(med_line)
        analogs = [m for m in (p.get("medications_analogs") or []) if m]
        if analogs:
            alt_line = "Аналоги препаратов: " + ", ".join(analogs[:5])
            if alt_line not in treatment:
                treatment.append(alt_line)
        for alt in (p.get("alternative_treatment") or [])[:2]:
            if any(k in alt.lower() for k in ["пит", "диет"]):
                if alt not in nutrition:
                    nutrition.append(alt)
            elif any(k in alt.lower() for k in ["актив", "нагруз", "ходьб", "упраж"]):
                if alt not in activity:
                    activity.append(alt)
            elif alt not in prevention:
                prevention.append(alt)

    q_low = text.lower()
    lab_mode = any(k in q_low for k in ("органическ", "ммоль", "креатинин", "метабол", "митохонд"))
    has_symptom_signal = _has_symptom_signal(text)
    drift_keys = _ACUTE_CLINICAL_DRIFT_KEYS
    if lab_mode and not has_symptom_signal:
        conclusions = [x for x in conclusions if not any(k in x.lower() for k in drift_keys)]
        diagnosis_hints = [x for x in diagnosis_hints if not any(k in x.lower() for k in drift_keys)]

    lab_deviations = _extract_lab_deviations(text)
    markers = _extract_numeric_markers(text)
    for m in markers:
        it = _interpret_marker(m)
        for x in it.get("findings") or []:
            if x not in marker_findings:
                marker_findings.append(x)
        for x in it.get("hypotheses") or []:
            if x not in marker_hypotheses:
                marker_hypotheses.append(x)
        for x in it.get("recommendations") or []:
            if x not in marker_recommendations:
                marker_recommendations.append(x)
        for x in it.get("diagnostics") or []:
            if x not in marker_diagnostics:
                marker_diagnostics.append(x)
        if m.get("status") == "high":
            severity = "YELLOW" if severity != "RED" else severity

    for x in marker_findings[:10]:
        if x not in conclusions:
            conclusions.append(x)
    for x in marker_hypotheses[:12]:
        if x not in diagnosis_hints:
            diagnosis_hints.append(x)
    for x in marker_recommendations[:12]:
        if x not in treatment:
            treatment.append(x)
    for x in marker_diagnostics[:10]:
        line = "Диагностика: " + x
        if line not in diagnosis_hints:
            diagnosis_hints.append(line)

    if lab_mode:
        # Strict lab mode: keep only document-grounded outputs from parsed markers.
        conclusions = list(marker_findings[:20])
        diagnosis_hints = list(marker_hypotheses[:20]) + [f"Диагностика: {x}" for x in marker_diagnostics[:10]]
        treatment = [x for x in marker_recommendations[:16]]
        # Suppress hallucinations for organic acids / metabolic docs
        _suppressed = (
            "липид", "холестер", "железодефицит", "анемия железодефици", "кортизол",
            "нарушение сна", "бессонниц", "гистамин", "непереносимость гистамина",
            "цистит", "пиелонефрит", "мигрен", "цитрус", "вин", "сыр", "шоколад",
        )
        def _not_suppressed(x: str) -> bool:
            low = str(x or "").lower()
            return not any(s in low for s in _suppressed)
        conclusions = [x for x in conclusions if _not_suppressed(x)]
        diagnosis_hints = [x for x in diagnosis_hints if _not_suppressed(x)]
        treatment = [x for x in treatment if _not_suppressed(x)]

    # Guard against unsupported vitamin D conclusions/hypotheses.
    if not _has_direct_vitamin_d_evidence(text):
        def _not_vitd(line: str) -> bool:
            low = str(line or "").lower()
            return ("витамин d" not in low) and ("витамина d" not in low) and ("25-oh" not in low) and ("25(oh)d" not in low)

        conclusions = [x for x in conclusions if _not_vitd(x)]
        diagnosis_hints = [x for x in diagnosis_hints if _not_vitd(x)]
        treatment = [x for x in treatment if _not_vitd(x)]
        nutrition = [x for x in nutrition if _not_vitd(x)]
        prevention = [x for x in prevention if _not_vitd(x)]

    if not conclusions and professional_offline:
        conclusions.append("По данным офлайн-справочника обнаружены релевантные темы. Рекомендуется консультация врача для интерпретации анализов.")

    modern_evidence, evidence_links = _fetch_modern_evidence(scenarios)

    return {
        "conclusions": conclusions,
        "diagnosis_hints": diagnosis_hints,
        "treatment": treatment,
        "nutrition": nutrition,
        "activity": activity,
        "prevention": prevention,
        "severity": severity,
        "offline_professional": professional_offline,
        "offline_simple": simple_offline,
        "modern_evidence": modern_evidence,
        "evidence_links": evidence_links,
        "marker_findings": marker_findings,
        "marker_hypotheses": marker_hypotheses,
        "marker_recommendations": marker_recommendations,
        "marker_diagnostics": marker_diagnostics,
        "markers": markers,
        "lab_deviations": lab_deviations,
    }


def _empty_analysis() -> dict[str, Any]:
    return {
        "conclusions": [],
        "diagnosis_hints": [],
        "treatment": [],
        "nutrition": [],
        "activity": [],
        "prevention": [],
        "severity": "GREEN",
        "offline_professional": "",
        "offline_simple": "",
        "modern_evidence": [],
        "evidence_links": [],
        "marker_findings": [],
        "marker_hypotheses": [],
        "marker_recommendations": [],
        "marker_diagnostics": [],
        "markers": [],
        "lab_deviations": [],
    }
