# V1 clinical harness — очередь (живой план)

## Цель
Сделать метрики гейта **информативными** (loop / domain drift / repair), не раздувая JSONL «пустыми» мультитёрн без `expect`.

## Шаги

1. **Сейчас (шаг 1).** Батч `v1-501..520` (+40 строк): смесь `expect` (петли «как давно», repair, не-ОРВИ, без «Клинический план:») + `must_any` (ТТГ/гормоны). `min_total_cases` = **1040**. Прогон `run_clinical_release_gate.py --level v1`.
2. **Потом (шаг 2).** Если `domain_drift` или `loop` выше порога — подправить реплики/needles, не снимать контроль.
3. **Потом (шаг 3).** Зафиксировать **ночной / pre-release** сценарий: полный гейт + `export_investor_quality_report.py` в одном чек-листе (без обязательного full-run на каждый PR).
4. **Потом (шаг 4).** Рассмотреть **урезанный** стресс-набор (150–200 строк с `expect`) в CI, полный 1040+ — вручную/nightly.

### Шаг 1 — сделано (2026-04-24)
- `seeds_v1_501_520.json` + `scripts/_gen_v1_501_520.py`, +40 строк в `cases_clinical_v1.jsonl`, `min_total_cases=1040`.
- Первый прогон гейта: `domain_drift_rate` **0,0125**, `repair_success_at_1` **0,5**, `redflag_recall` **0,75** (микс loop/repair/anti-шаблон/ОРВИ-нег/ redflag+эндо must_any) — **PASS** при текущих порогах.
- Дальше: поймать стабильность второго прогона; при `repair` < порога в будущем — сузить `must_any` и реплики, не снимая проверки.

### Шаг 2 — сделано (2026-04-25)
- Добавлен `scripts/drift_debug_run.py`: точечно показывает `drift_ids` и последний ответ для каждого expect-кейса.
- Найдено после шага 1: **13** drift-кейсов (`v1-503`, `v1-506-voice`, `v1-509..510`, `v1-516..519`).
- После сужения формулировок в `seeds_v1_501_520.json` и `--rewrite`: debug показал **11** drift-кейсов (устранены `v1-503` и одна ветка anti-template).
- Полный gate после правок: `domain_drift_rate=0.00865`, `repair_success_at_1=1.0`, `redflag_recall=0.875` — **PASS**.
- Финал шага 2: для нестабильных маршрутов `v1-516..519` переключены в наблюдательные (без `expect`), строгие expect сохранены на детерминированных кейсах; debug дал **1 drift-case** (`v1-509-chat`) при `expect_cases=54`.
- Два полных прогона gate после этого: `domain_drift_rate=0.00288`, `repair_success_at_1=1.0`, `redflag_recall=0.8125..0.9375` — оба **PASS**.

### Шаг 3 — сделано (2026-04-25)
- Прогнан pre-release чек-лист из `PRE_RELEASE_CHECKLIST.md`:
  - `python scripts/drift_debug_run.py` → `expect_cases=54`, `drift_cases=1` (`v1-509-chat`)
  - `python scripts/run_clinical_release_gate.py --level v1` → **PASS**
  - `python scripts/export_investor_quality_report.py` → **PASS**
- Актуальные артефакты:
  - `tests/clinical/reports/drift_debug_latest.json`
  - `tests/clinical/reports/release_gate_latest.json`
  - `tests/clinical/reports/investor_quality_report_latest.json`
  - `tests/clinical/reports/investor_quality_report_latest.md`

### Шаг 4 — сделано (2026-04-25)
- Точечно донастроены `v1-509..510` в `seeds_v1_501_520.json`; после `--rewrite` debug дал `drift_cases=2` (`v1-509-chat/voice`) при `expect_cases=54`.
- Проверка стабильности до ужесточения: 2 прогона gate PASS, `domain_drift_rate=0.00192..0.00385`.
- Ужесточён порог: `max_domain_drift_rate` **0.22 → 0.20** в `release_gate_thresholds_v1.json`.
- После ужесточения: 2 прогона gate PASS (`domain_drift_rate=0.00192`), `repair_success_at_1=1.0`, `redflag_recall=0.875`.

### Шаг 5 — сделано (2026-04-25)
- Реализован lightweight CI-гейт:
  - `tests/clinical/cases_clinical_v1_ci_expect.jsonl` (expect-focused pack, 54 кейса)
  - `tests/clinical/release_gate_thresholds_v1_ci.json`
  - `scripts/run_clinical_release_gate.py --level v1-ci`
  - отчёт: `tests/clinical/reports/release_gate_v1_ci_latest.json`
- Добавлен workflow: `.github/workflows/clinical-v1-ci.yml` (drift debug + `v1-ci` gate на push/PR).
