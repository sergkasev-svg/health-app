"""
Universal Multi-Lab Engine: один вход (raw_text + lab_markers + symptoms) → автоопределение типа → нужный движок.
Поддерживает: lipid_panel, organic_acids, cbc, urinalysis, liver_panel, biochemistry.
Не отказывает с «не тот анализ», в unknown-case возвращает честный ответ.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            value = value.replace(",", ".").strip()
        return float(value)
    except Exception:
        return None


def detect_report_type(text: str) -> str:
    t = (text or "").lower()

    if any(x in t for x in ["липидный профиль", "холестерин", "лпнп", "лпвп", "триглицерид"]):
        return "lipid_panel"
    if any(x in t for x in ["органических кислот", "organic acids", "figlu", "пироглутаминов", "малоновая кислота"]):
        return "organic_acids"
    if any(x in t for x in ["общий анализ крови", "гемоглобин", "эритроцит", "лейкоцит", "тромбоцит", "соэ"]):
        return "cbc"
    if any(x in t for x in ["общий анализ мочи", "белок в моче", "лейкоциты в моче", "нитрит", "эритроциты в моче"]):
        return "urinalysis"
    if any(x in t for x in ["алт", "аст", "ggt", "ггт", "щелочная фосфатаза", "билирубин", "печеноч", "печёноч"]):
        return "liver_panel"
    if any(x in t for x in ["глюкоза", "креатинин", "мочевина", "ферритин", "витамин d", "биохимия"]):
        return "biochemistry"
    return "unknown"


def run_universal_multi_lab_engine(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_text = payload.get("raw_text", "") or ""
    report_type = payload.get("report_type") or detect_report_type(raw_text)
    markers = payload.get("lab_markers", {}) or {}
    symptoms = payload.get("symptoms", []) or []

    if report_type == "lipid_panel":
        result = run_lipid_engine(markers, symptoms)
    elif report_type == "organic_acids":
        result = run_organic_acids_engine(markers, symptoms)
    elif report_type == "cbc":
        result = run_cbc_engine(markers, symptoms)
    elif report_type == "urinalysis":
        result = run_urinalysis_engine(markers, symptoms)
    elif report_type == "liver_panel":
        result = run_liver_engine(markers, symptoms)
    elif report_type == "biochemistry":
        result = run_biochemistry_engine(markers, symptoms)
    else:
        result = run_unknown_engine(raw_text)

    result["report_type"] = report_type
    return result


def run_lipid_engine(markers: Dict[str, Any], symptoms: List[str]) -> Dict[str, Any]:
    ldl = _to_float(markers.get("ldl"))
    total = _to_float(markers.get("cholesterol_total"))
    hdl = _to_float(markers.get("hdl"))
    tg = _to_float(markers.get("triglycerides"))

    findings: List[str] = []
    meaning: List[str] = []
    actions: List[str] = []
    tests: List[str] = []

    if ldl is not None and ldl > 3.0:
        findings.append(f"Повышен ЛПНП: {ldl:.2f}")
        meaning.append("ЛПНП выше целевого уровня и может повышать сердечно-сосудистый риск.")
    if total is not None and total > 5.2:
        findings.append(f"Повышен общий холестерин: {total:.2f}")
        meaning.append("Общий холестерин повышен, что требует оценки в контексте LDL, семейного риска и образа жизни.")
    if hdl is not None and hdl > 1.2:
        findings.append(f"ЛПВП не снижен: {hdl:.2f}")
        meaning.append("Защитная фракция холестерина не снижена, но это не отменяет значимость высокого ЛПНП.")
    if tg is not None and tg <= 2.3:
        findings.append(f"Триглицериды без значимого повышения: {tg:.2f}")

    actions.extend([
        "Оценить рацион: меньше ультрапереработанной пищи и избытка насыщенных жиров, больше цельных продуктов.",
        "Добавить регулярную физическую активность, если нет противопоказаний.",
        "Сравнить результат с предыдущими анализами и семейным анамнезом по инфарктам/инсультам."
    ])
    tests.extend([
        "ApoB",
        "Липопротеин(a)",
        "Глюкоза / HbA1c",
        "ТТГ при подозрении на вторичные причины"
    ])

    text = _render_response(
        title="Липидный профиль",
        findings=findings,
        meaning=meaning,
        actions=actions,
        tests=tests,
        safety="Это не диагноз. При стойко высоком ЛПНП нужен очный разбор с врачом и оценка общего сердечно-сосудистого риска."
    )
    return {"text": text, "findings": findings, "tests": tests}


def run_organic_acids_engine(markers: Dict[str, Any], symptoms: List[str]) -> Dict[str, Any]:
    pyro = str(markers.get("pyroglutamic", "")).lower() == "high"
    malonic = str(markers.get("malonic", "")).lower() == "high"
    sebacic = str(markers.get("sebacic", "")).lower() == "high"
    figlu = str(markers.get("figlu", "")).lower() == "high"
    hippuric = str(markers.get("hippuric", "")).lower() == "high"
    mandelic = str(markers.get("mandelic", "")).lower() == "high"

    findings: List[str] = []
    meaning: List[str] = []
    actions: List[str] = []
    tests: List[str] = []

    if pyro:
        findings.append("Есть признаки окислительного стресса / напряжения глутатионового обмена.")
        meaning.append("Это может ухудшать восстановление и повышать чувствительность к нагрузке.")
        actions.append("Снизить внешнюю нагрузку и обсудить с врачом антиоксидантную поддержку.")
    if malonic or sebacic:
        findings.append("Есть признаки напряжения энергообмена и/или β-окисления жирных кислот.")
        meaning.append("Это может сопровождаться слабостью, утомляемостью и плохой переносимостью длительных пауз в еде.")
        actions.append("Нормализовать режим питания, не делать длинных голодных пауз, оценить достаточность калорий и жиров.")
    if figlu:
        findings.append("Есть возможный вклад B9/B12-зависимых дефицитных состояний.")
        meaning.append("Такой паттерн требует подтверждения лабораторно, а не слепой коррекции.")
        tests.extend(["B12", "Фолиевая кислота", "Гомоцистеин"])
    if hippuric or mandelic:
        findings.append("Есть признаки внешней метаболической нагрузки.")
        meaning.append("Это может быть связано с рационом, добавками, бытовой химией, лекарственным или средовым фактором.")
        actions.append("Пересмотреть БАДы, бытовую химию, ароматизаторы, ультрапереработанную пищу.")

    if not findings:
        findings.append("Нет явного паттерна, требующего отдельной автоматической гипотезы по этому набору маркеров.")

    actions.extend([
        "Оценить самочувствие, переносимость интервалов между едой и динамику симптомов.",
        "Сопоставить с реальным рационом и лекарственным фоном."
    ])

    text = _render_response(
        title="Органические кислоты",
        findings=findings,
        meaning=meaning,
        actions=actions,
        tests=tests,
        safety="Автоматическая интерпретация органических кислот не заменяет очный разбор. Итог зависит от клиники, рациона, лекарств и исходного бланка."
    )
    return {"text": text, "findings": findings, "tests": tests}


def run_cbc_engine(markers: Dict[str, Any], symptoms: List[str]) -> Dict[str, Any]:
    hb = _to_float(markers.get("hb"))
    mch = _to_float(markers.get("mch"))
    mcv = _to_float(markers.get("mcv"))
    rdw = _to_float(markers.get("rdw"))
    wbc = _to_float(markers.get("wbc"))
    neut = _to_float(markers.get("neutrophils"))
    eos = _to_float(markers.get("eosinophils"))
    plt = _to_float(markers.get("platelets"))
    ret_abs = _to_float(markers.get("reticulocytes_abs"))

    findings: List[str] = []
    meaning: List[str] = []
    actions: List[str] = []
    tests: List[str] = []

    if hb is not None and hb < 120:
        findings.append(f"Гемоглобин снижен: {hb:.0f}")
        meaning.append("Это может соответствовать анемии или дефицитному состоянию.")
        tests.extend(["Ферритин", "B12", "Фолат", "Ретикулоциты"])
    if hb is not None and hb < 125 and (mch is None or mch < 27):
        findings.append(f"Гемоглобин у нижней границы" + (f", MCH снижен: {mch:.1f}" if mch is not None else ""))
        meaning.append("Возможен ранний железодефицит или гипопролиферативный эритропоэз.")
        if "Ферритин" not in tests:
            tests.extend(["Ферритин", "Сывороточное железо", "ОЖСС"])
    if mch is not None and mch < 27:
        findings.append(f"MCH снижен: {mch:.1f}")
        meaning.append("Сниженное содержание гемоглобина в эритроците.")
    if ret_abs is not None and ret_abs < 50:
        findings.append(f"Ретикулоциты абс. снижены: {ret_abs:.1f}")
        meaning.append("Сниженная регенераторная активность эритропоэза.")
        if "Ферритин" not in tests:
            tests.append("Ферритин")
    if hb is not None and mcv is not None and hb < 120 and mcv < 80:
        findings.append("Есть микроцитарный паттерн.")
        meaning.append("Чаще так выглядит железодефицитный профиль или хроническая кровопотеря.")
    if hb is not None and mcv is not None and hb < 120 and mcv > 96:
        findings.append("Есть макроцитарный паттерн.")
        meaning.append("Нужно исключать дефицит B12/фолата, влияние печени, алкоголя или лекарств.")
    if rdw is not None and rdw > 14.5:
        findings.append("RDW повышен.")
        meaning.append("Это может говорить о смешанном дефиците или формирующемся дефицитном состоянии.")
    if wbc is not None and wbc > 9.5:
        findings.append(f"Лейкоциты повышены: {wbc:.1f}")
        meaning.append("Это может соответствовать инфекции, воспалению, стресс-реакции или влиянию лекарств.")
    if neut is not None and neut > 70:
        findings.append("Нейтрофилы повышены.")
        meaning.append("Чаще бывает при бактериальном воспалении или стресс-реакции.")
    if eos is not None and eos > 5:
        findings.append("Эозинофилы повышены.")
        meaning.append("Нужно думать об аллергическом фоне, паразитозах или лекарственной реакции.")
    if plt is not None and plt < 150:
        findings.append("Тромбоциты снижены.")
        meaning.append("Требует осторожной оценки, особенно при кровоточивости.")
    elif plt is not None and plt > 400:
        findings.append("Тромбоциты повышены.")
        meaning.append("Могут повышаться реактивно: при воспалении, дефиците железа, после кровопотери.")

    if not findings:
        findings.append("Нет выраженного автоматического паттерна по загруженным CBC-маркерам.")

    actions.extend([
        "Сопоставить показатели с жалобами, температурой, менструацией/кровопотерей, лекарствами.",
        "Сравнить с предыдущими анализами в динамике."
    ])

    text = _render_response(
        title="Общий анализ крови",
        findings=findings,
        meaning=meaning,
        actions=actions,
        tests=tests,
        safety="Это не диагноз. При выраженной слабости, кровоточивости, высокой температуре или резко изменённых показателях нужна очная оценка."
    )
    return {"text": text, "findings": findings, "tests": tests}


def run_urinalysis_engine(markers: Dict[str, Any], symptoms: List[str]) -> Dict[str, Any]:
    protein = str(markers.get("protein", "")).lower()
    leuk = str(markers.get("leukocytes", "")).lower()
    nitrites = str(markers.get("nitrites", "")).lower()
    blood = str(markers.get("blood", "")).lower()
    glucose = str(markers.get("glucose", "")).lower()
    ketones = str(markers.get("ketones", "")).lower()

    findings: List[str] = []
    meaning: List[str] = []
    actions: List[str] = []
    tests: List[str] = []

    if protein in ("positive", "high", "trace"):
        findings.append("Есть белок в моче.")
        meaning.append("Это может быть временно после нагрузки/лихорадки, но при повторении требует проверки почечного контекста.")
    if leuk in ("positive", "high"):
        findings.append("Есть лейкоциты в моче.")
        meaning.append("Может соответствовать воспалению мочевых путей или плохому сбору анализа.")
    if nitrites in ("positive", "high"):
        findings.append("Нитриты положительные.")
        meaning.append("Это усиливает вероятность бактериальной инфекции мочевых путей.")
    if blood in ("positive", "high"):
        findings.append("Есть кровь / эритроциты в моче.")
        meaning.append("Нужно учитывать сбор, менструацию, камни, инфекцию и почечные причины.")
    if glucose in ("positive", "high"):
        findings.append("Есть глюкоза в моче.")
        meaning.append("Нужно проверить уровень глюкозы крови и исключать нарушения углеводного обмена.")
    if ketones in ("positive", "high"):
        findings.append("Есть кетоны в моче.")
        meaning.append("Может быть при голодании, рвоте, температуре, плохом питании или диабетическом контексте.")

    if not findings:
        findings.append("Нет выраженного автоматического паттерна по загруженным мочевым маркерам.")

    actions.extend([
        "Уточнить, как собирался анализ, и были ли симптомы: боль, жжение, температура, частое мочеиспускание.",
        "При сомнительном отклонении повторить анализ с правильным сбором."
    ])
    tests.extend(["Повторный ОАМ", "Посев мочи — если есть симптомы инфекции"])

    text = _render_response(
        title="Общий анализ мочи",
        findings=findings,
        meaning=meaning,
        actions=actions,
        tests=tests,
        safety="Это не диагноз. При боли, температуре, крови в моче, отёках или высоком давлении нужна очная оценка."
    )
    return {"text": text, "findings": findings, "tests": tests}


def run_liver_engine(markers: Dict[str, Any], symptoms: List[str]) -> Dict[str, Any]:
    alt = _to_float(markers.get("alt"))
    ast = _to_float(markers.get("ast"))
    ggt = _to_float(markers.get("ggt"))
    alp = _to_float(markers.get("alp"))
    bili = _to_float(markers.get("bilirubin_total"))

    findings: List[str] = []
    meaning: List[str] = []
    actions: List[str] = []
    tests: List[str] = []

    if alt is not None and alt > 40:
        findings.append(f"АЛТ повышен: {alt:.1f}")
        meaning.append("Это может отражать нагрузку на печень, жировую болезнь печени, лекарственный или иной гепатоцеллюлярный контекст.")
    if ast is not None and ast > 40:
        findings.append(f"АСТ повышен: {ast:.1f}")
        meaning.append("Повышение АСТ оценивают вместе с АЛТ, мышечной нагрузкой и клиникой.")
    if ggt is not None and ggt > 60:
        findings.append(f"ГГТ повышен: {ggt:.1f}")
        meaning.append("Это поддерживает гепатобилиарный источник отклонений или влияние лекарств/алкоголя.")
    if alp is not None and alp > 120:
        findings.append(f"ЩФ повышена: {alp:.1f}")
        meaning.append("Нужно различать гепатобилиарный и костный контекст, особенно у детей.")
    if bili is not None and bili > 21:
        findings.append(f"Билирубин повышен: {bili:.1f}")
        meaning.append("Нужно учитывать синдром Жильбера, гемолиз, холестаз и печёночный контекст.")

    if not findings:
        findings.append("Нет выраженного автоматического печёночного паттерна по загруженным маркерам.")

    actions.extend([
        "Сопоставить анализ с лекарствами, алкоголем, весом, УЗИ-контекстом и физической нагрузкой.",
        "При лёгком отклонении полезна повторная проверка в динамике."
    ])
    tests.extend(["Повторить АЛТ/АСТ/ГГТ", "УЗИ печени — по показаниям", "HBsAg / anti-HCV — по клинической необходимости"])

    text = _render_response(
        title="Печёночный профиль",
        findings=findings,
        meaning=meaning,
        actions=actions,
        tests=tests,
        safety="Это не диагноз. При желтухе, тёмной моче, светлом стуле, сильной боли или резко высоких ферментах нужен срочный очный разбор."
    )
    return {"text": text, "findings": findings, "tests": tests}


def run_biochemistry_engine(markers: Dict[str, Any], symptoms: List[str]) -> Dict[str, Any]:
    glucose = _to_float(markers.get("glucose"))
    ferritin = _to_float(markers.get("ferritin"))
    creatinine = _to_float(markers.get("creatinine"))
    vitamin_d = _to_float(markers.get("vitamin_d"))

    findings: List[str] = []
    meaning: List[str] = []
    actions: List[str] = []
    tests: List[str] = []

    if glucose is not None and glucose > 5.6:
        findings.append(f"Глюкоза выше желаемого уровня: {glucose:.1f}")
        meaning.append("Нужно оценить углеводный обмен и контекст натощак / не натощак.")
        tests.append("HbA1c")
    if ferritin is not None and ferritin < 30:
        findings.append(f"Ферритин снижен: {ferritin:.1f}")
        meaning.append("Это может соответствовать дефициту железа даже до выраженной анемии.")
        tests.extend(["ОАК", "Железо / ОЖСС — по показаниям"])
    if creatinine is not None and creatinine > 100:
        findings.append(f"Креатинин повышен: {creatinine:.0f}")
        meaning.append("Нужно оценивать вместе с eGFR, гидратацией, мышечной массой и лекарствами.")
        tests.append("eGFR")
    if vitamin_d is not None and vitamin_d < 30:
        findings.append(f"Витамин D снижен: {vitamin_d:.1f}")
        meaning.append("Это может быть фактором общего дефицитного фона, но интерпретируется вместе с клиникой и рисками.")

    if not findings:
        findings.append("Нет выраженного автоматического паттерна по загруженной базовой биохимии.")

    actions.extend([
        "Сопоставить показатели с жалобами и повторить ключевые показатели при необходимости.",
        "Не делать выводов по одному маркеру без общего контекста."
    ])

    text = _render_response(
        title="Базовая биохимия",
        findings=findings,
        meaning=meaning,
        actions=actions,
        tests=tests,
        safety="Это не диагноз. Интерпретация зависит от симптомов, натощак/не натощак, лекарств и общей картины."
    )
    return {"text": text, "findings": findings, "tests": tests}


def run_unknown_engine(raw_text: str) -> Dict[str, Any]:
    text = (
        "🧠 Что произошло\n"
        "- Система не смогла уверенно определить тип анализа.\n\n"
        "⚡ Что это значит\n"
        "- Нужен либо более качественный исходный документ, либо отдельный парсер под этот тип бланка.\n\n"
        "🚀 Что делать\n"
        "- Сохранить распознанный текст.\n"
        "- Определить тип анализа по ключевым словам.\n"
        "- Подключить отдельный движок интерпретации.\n\n"
        "⚠️ Важно\n"
        "- Не возвращай пустой ответ. Даже в unknown-case система должна честно сказать, что именно не распознано."
    )
    return {"text": text, "findings": ["Тип анализа не определён"], "tests": []}


def _render_response(title: str, findings: List[str], meaning: List[str], actions: List[str], tests: List[str], safety: str) -> str:
    lines = [f"📄 {title}", "", "🧠 Что происходит"]
    lines.extend(f"- {x}" for x in findings[:6])

    if meaning:
        lines.append("")
        lines.append("⚡ Что это значит")
        lines.extend(f"- {x}" for x in meaning[:6])

    if actions:
        lines.append("")
        lines.append("🚀 Что делать")
        lines.extend(f"- {x}" for x in actions[:6])

    if tests:
        lines.append("")
        lines.append("🧪 Что проверить")
        lines.extend(f"- {x}" for x in tests[:6])

    lines.append("")
    lines.append("⚠️ Важно")
    lines.append(f"- {safety}")
    return "\n".join(lines)
