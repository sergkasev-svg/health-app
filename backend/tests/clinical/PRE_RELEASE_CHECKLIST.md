# Clinical V1 Pre-release Checklist

1) Обновить сиды/кейс-паки при необходимости:
- `python scripts/_gen_v1_501_520.py --rewrite`

2) Диагностика drift по expect-кейсам:
- `python scripts/drift_debug_run.py`
- Проверить `tests/clinical/reports/drift_debug_latest.json`

3) Лёгкий CI-gate (expect-focused):
- `python scripts/run_clinical_release_gate.py --level v1-ci`
- Проверить `tests/clinical/reports/release_gate_v1_ci_latest.json`

4) Полный release gate:
- `python scripts/run_clinical_release_gate.py --level v1`

5) Investor отчёт:
- `python scripts/export_investor_quality_report.py`

6) Артефакты для фиксации:
- `tests/clinical/reports/release_gate_v1_ci_latest.json`
- `tests/clinical/reports/release_gate_latest.json`
- `tests/clinical/reports/investor_quality_report_latest.json`
- `tests/clinical/reports/investor_quality_report_latest.md`
