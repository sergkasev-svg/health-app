from __future__ import annotations

from typing import Any, Dict, List, Set


def _normalize_flags(flags: Set[str]) -> Set[str]:
    out = set(flags or set())
    aliases = {
        "urine_leukocytes_positive": "urine_leukocytes_high",
        "omega_3_low": "omega3_index_low",
        "aa_epa_high": "aa_epa_ratio_high",
        "omega6_omega3_high": "omega6_3_ratio_high",
    }
    for src, dst in aliases.items():
        if src in out:
            out.add(dst)
    return out


def autolink_knowledge(payload: Dict[str, Any]) -> Dict[str, Any]:
    flags = _normalize_flags(set(payload.get("lab_flags") or []))
    out = {
        "knowledge_sources": [],
        "knowledge_topics": [],
        "brain_enhance": {
            "hypotheses": [],
            "interpretation": [],
            "what_to_add": [],
            "nutrition": [],
            "supplements": [],
            "activity": [],
            "red_flags": [],
        },
    }

    def add_source(name: str) -> None:
        if name not in out["knowledge_sources"]:
            out["knowledge_sources"].append(name)

    def add_topic(topic: str) -> None:
        if topic not in out["knowledge_topics"]:
            out["knowledge_topics"].append(topic)

    def add_enh(field: str, lines: List[str]) -> None:
        bucket = out["brain_enhance"].get(field) or []
        for line in lines:
            s = str(line or "").strip()
            if s and s not in bucket:
                bucket.append(s)
        out["brain_enhance"][field] = bucket

    # Blood
    if {"hb_low", "mcv_low", "ferritin_low"} & flags:
        add_source("knowledge_blood_prompt.txt")
        add_topic("железо")
        add_topic("эритропоэз")
        add_topic("ретикулоциты")
        add_topic("дефицитные анемии")
        add_enh("what_to_add", ["Ферритин, трансферрин, насыщение трансферрина, ретикулоциты в динамике."])
        add_enh("interpretation", ["Паттерн может соответствовать дефицитному эритропоэзу и требует клинической оценки."])

    if {"hb_low", "mcv_high", "figlu_high", "methylmalonic_high"} & flags:
        add_source("knowledge_blood_prompt.txt")
        add_source("knowledge_organic_acids_prompt.txt")
        add_topic("B12")
        add_topic("B9")
        add_topic("макроцитоз")
        add_topic("коферменты")
        add_enh("what_to_add", ["Уточнить B12, фолаты, гомоцистеин; при необходимости повторить органические кислоты."])

    if {"esr_high", "crp_high", "wbc_high", "neutrophils_high"} & flags:
        add_source("knowledge_blood_prompt.txt")
        add_topic("воспаление")
        add_topic("белки острой фазы")
        add_topic("церулоплазмин")
        add_topic("фибриноген")
        add_enh("interpretation", ["Изолированные воспалительные маркеры трактуются как сигнал контекста, а не диагноз."])
        add_enh("what_to_add", ["Оценить клинику, CRP/БОФ в динамике и очные признаки воспаления."])

    if {"ldl_high", "triglycerides_high", "hdl_low", "apoB_high"} & flags:
        add_source("knowledge_blood_prompt.txt")
        add_source("knowledge_fatty_acids_prompt.txt")
        add_topic("липидный риск")
        add_topic("атерогенный профиль")
        add_enh("nutrition", ["Ограничить ультрапереработанные продукты и увеличить долю клетчатки/цельных продуктов."])
        add_enh("activity", ["Регулярная аэробная нагрузка по переносимости и согласованию с врачом."])

    # Urine / organic acids
    if {"urine_leukocytes_high", "urine_nitrites_positive", "urine_blood_positive", "urine_protein_positive"} & flags:
        add_source("knowledge_urine_prompt.txt")
        add_topic("инфекция мочевых путей")
        add_topic("протеинурия")
        add_topic("гематурия")
        add_topic("сбор анализа")
        add_enh("what_to_add", ["Повтор ОАМ с корректным сбором; при показаниях — посев мочи и очная оценка."])
        add_enh("red_flags", ["Боль в пояснице, лихорадка, видимая кровь в моче — повод для срочного обращения."])

    if {"pyroglutamic_high", "malonic_high", "sebacic_high", "figlu_high", "methylmalonic_high", "mitochondrial_markers"} & flags:
        add_source("knowledge_organic_acids_prompt.txt")
        add_topic("митохондрии")
        add_topic("глутатион")
        add_topic("β-окисление")
        add_topic("коферменты")
        add_enh("nutrition", ["Регулярные приемы пищи без длительных голодных интервалов при сниженной переносимости."])
        add_enh("supplements", ["Кофакторную поддержку обсуждать только после подтверждения дефицитного паттерна."])

    # Stool / microbiome
    if {"calprotectin_high", "elastase_low", "occult_blood_positive"} & flags:
        add_source("knowledge_stool_prompt.txt")
        add_topic("кишечное воспаление")
        add_topic("переваривание")
        add_topic("ферменты")
        add_enh("what_to_add", ["Контроль кальпротектина/эластазы в динамике и очная гастрооценка по показаниям."])
        add_enh("red_flags", ["Скрытая кровь в кале требует приоритетного дообследования."])

    if {"microbiome_dysbiosis", "roseburia_low", "butyrate_low"} & flags:
        add_source("knowledge_microbiome_prompt.txt")
        add_topic("бутират")
        add_topic("gut-brain")
        add_topic("gut-muscle")
        add_topic("barrier integrity")
        add_enh("nutrition", ["Пошагово увеличить пищевые волокна и пребиотики по переносимости."])

    # Saliva
    if "cortisol_pattern_abnormal" in flags:
        add_source("knowledge_saliva_prompt.txt")
        add_topic("стресс-ось")
        add_topic("сон")
        add_topic("нагрузка")
        add_enh("activity", ["Нормализовать режим сна/нагрузки и избегать перетренированности до уточнения контекста."])

    # Skin / mucosa
    if {"skin_inflammation", "pcr_positive", "dysbiosis", "recurrent_inflammation"} & flags:
        add_source("knowledge_skin_mucosa_prompt.txt")
        add_source("knowledge_microbiome_prompt.txt")
        add_topic("локальное воспаление")
        add_topic("инфекционные панели")
        add_topic("кишечник-кожа")
        add_enh("what_to_add", ["Уточнить локальные триггеры, системные дефициты и микробиомный контекст по показаниям."])

    # Fatty acids
    if {"omega3_index_low", "aa_epa_ratio_high", "omega6_3_ratio_high"} & flags:
        add_source("knowledge_fatty_acids_prompt.txt")
        add_topic("омега-3 индекс")
        add_topic("AA/EPA")
        add_topic("воспалительный жирнокислотный паттерн")
        add_enh("nutrition", ["Скорректировать баланс пищевых жиров с фокусом на омега-3 источники."])

    return out
