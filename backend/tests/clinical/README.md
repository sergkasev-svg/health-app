# Clinical Harness Quick Guide

Короткий справочник по уровням клинического gate и порядку запуска.

## Уровни gate

- `starter` — быстрый базовый sanity-check на небольшом паке.
- `v1-ci` — облегчённый expect-focused gate для CI (быстрый и информативный по drift/repair).
- `v1` — полный gate на расширенном паке (release/nightly).

## Команды

Из каталога `backend/`:

```bash
python scripts/run_clinical_release_gate.py --level starter
python scripts/run_clinical_release_gate.py --level v1-ci
python scripts/run_clinical_release_gate.py --level v1
```

Диагностика drift по expect-кейсам:

```bash
python scripts/drift_debug_run.py
```

Обновление investor quality отчёта:

```bash
python scripts/export_investor_quality_report.py
```

## Когда что запускать

- PR/CI: `v1-ci` (+ при необходимости `drift_debug_run.py`)
- Перед релизом: `v1` + `export_investor_quality_report.py`
- Отладка нестабильностей: `drift_debug_run.py`, затем точечная правка сидов/expect.

## Основные файлы

- Full pack: `tests/clinical/cases_clinical_v1.jsonl`
- CI pack: `tests/clinical/cases_clinical_v1_ci_expect.jsonl`
- V1 thresholds: `tests/clinical/release_gate_thresholds_v1.json`
- V1-CI thresholds: `tests/clinical/release_gate_thresholds_v1_ci.json`
- Latest reports: `tests/clinical/reports/`

## Связанные документы

- План/история шагов: `tests/clinical/HARNESS_NEXT_STEPS.md`
- Pre-release чек-лист: `tests/clinical/PRE_RELEASE_CHECKLIST.md`
- Эталонный срез: `tests/clinical/RELEASE_SLICE_2026-04-25.md`
