# Clinical Engine — путь миграции

## Пять правил продукта

1. **Запрет ложного fallback**: при ≥3 валидных показателях, числовых значениях и референсах нельзя писать «нет значимых отклонений», «нет гипотез», «только очная консультация».
2. **Заголовок отчёта только от final document_type**: иначе в заголовке всплывают органические кислоты там, где их нет.
3. **Один canonical findings registry**: summary, key_findings, working_hypotheses, next_steps строятся только из него.
4. **Contextual limitations only**: про железо, органические кислоты, ферритин — только если реально активировался соответствующий профиль.
5. **Regression suite на реальных бланках**: CBC, биохимия крови, липиды, органические кислоты — гонять после каждого изменения.

## Что сделано

1. **Новый пакет `app/services/clinical_engine/`**
   - `contracts.py` — DocumentType, LabValue, Finding, ReportModel
   - `classifier.py` — rule-based: biochemistry_blood при ≥3 маркерах; organic_acids только при явной сигнатуре
   - `normalizer.py` — ALIASES для канонических кодов маркеров
   - `extractor.py` — извлечение биохимии (липиды, HbA1c, фруктозамин, CRP, ApoB, Lp(a) и т.д.)
   - `router.py` — document_type + values → profile (lipid_panel, biochemistry_blood)
   - `rules/lipid_rules.py` — total_cholesterol > 7, ldl > 5, elevated_ldl, low_hdl, triglycerides
   - `rules/glucose_rules.py` — fructosamine elevated при нормальном HbA1c
   - `risk_synthesizer.py` — findings → summary, working_hypotheses, next_steps, limitations
   - `report_builder.py` — один canonical findings → ReportModel
   - `text_templates.py` — title/subtitle только по document_type/profile
   - `pipeline.py` — run_blood_biochemistry_pipeline(), report_model_to_legacy_dict()

2. **Интеграция**
   - В `document_physician_report.build_document_physician_report()` первым шагом вызывается `run_blood_biochemistry_pipeline(extracted)`. При успехе возвращается legacy-словарь из ReportModel. Только при отсутствии результата выполняется прежняя цепочка (organic_acids, lipid_engine, cbc, generic).

3. **Тесты**
   - `tests/test_clinical_engine_classifier.py` — биохимия не как organic_acids; organic_acids только по явной сигнатуре
   - `tests/test_clinical_engine_regression.py` — кейс chol 9.54, LDL 6.09 → biochemistry_blood, findings, без fallback
   - `tests/test_clinical_engine_report_consistency.py` — консистентность findings/summary/hypotheses, title по document_type
   - `tests/test_clinical_engine_integration.py` — build_document_physician_report с текстом биохимии возвращает biochemistry_blood

## Где раньше ломались связи

- **Classifier**: organic_phrases проверялись первыми; общие фразы («маркеры метаболизма») давали organic_acids для биохимии. Теперь сначала считается число маркеров биохимии (≥3 → biochemistry_blood).
- **Router**: не было явного профиля lipid_panel поверх biochemistry_blood; теперь profile = get_profile(doc_type, values).
- **Rules**: пороги LDL > 5 и total_cholesterol > 7 не использовались в едином findings; теперь в lipid_rules и glucose_rules.
- **Report**: summary и hypotheses собирались местами из разных источников; теперь один источник — findings, risk_synthesizer строит summary/hypotheses/next_steps из них.
- **Renderer/fallback**: при наличии данных выдавался generic «нет значимых отклонений»; теперь при успешном pipeline такого вывода нет, т.к. summary строится только из findings.

## Расширение

- Добавить профили в `profiles/` (cbc.py, thyroid_panel.py, urinalysis.py, organic_acids_urine.py) и вызывать их из pipeline по profile.
- Добавить правила в `rules/` (inflammation_rules, iron_rules, reticulocyte_rules) и подключать по профилю.
- Постепенно переводить organic_acids и CBC на те же контракты (ReportModel, Finding), затем отключить старые ветки в build_document_physician_report.
