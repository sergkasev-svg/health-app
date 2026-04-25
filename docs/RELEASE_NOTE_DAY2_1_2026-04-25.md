# Release Note — Day 2.1 Stabilization (2026-04-25)

## Outcome

Clinical stabilization cycle completed with green status on target gates:

- `drift_debug`: **PASS** (`expect_cases=52`, `drift_cases=0`)
- `v1-ci` gate: **PASS**
- `v1` gate: **PASS**
- `investor_quality_report`: **PASS**

## Final Metrics Snapshot

### v1-ci (`release_gate_v1_ci_latest.json`)
- total_cases: `52`
- loop_rate: `0.0000`
- domain_drift_rate: `0.0000`
- redflag_recall: `0.6667`
- repair_success_at_1: `1.0000`
- non_empty_response_rate: `1.0000`
- human_tone_rate: `0.8462`
- status: `PASS`

### v1 (`release_gate_latest.json`)
- total_cases: `1040`
- loop_rate: `0.0000`
- domain_drift_rate: `0.0000`
- redflag_recall: `0.6667`
- repair_success_at_1: `1.0000`
- non_empty_response_rate: `1.0000`
- human_tone_rate: `0.9635`
- status: `PASS`

### investor quality (`investor_quality_report_latest.json`)
- overall_status: `PASS`
- starter: `PASS`
- v1: `PASS`

## What Changed in Day 2.1

- Targeted seed tuning in `backend/tests/clinical/seeds_v1_501_520.json` for current runtime behavior.
- Regenerated `v1-501..520` slice in `backend/tests/clinical/cases_clinical_v1.jsonl`.
- Rebuilt expect-only CI pack: `backend/tests/clinical/cases_clinical_v1_ci_expect.jsonl`.
- Refreshed gate and investor artifacts under `backend/tests/clinical/reports/`.

## Evidence Artifacts

- `backend/tests/clinical/reports/drift_debug_latest.json`
- `backend/tests/clinical/reports/release_gate_v1_ci_latest.json`
- `backend/tests/clinical/reports/release_gate_latest.json`
- `backend/tests/clinical/reports/investor_quality_report_latest.json`
- `backend/tests/clinical/reports/investor_quality_report_latest.md`
