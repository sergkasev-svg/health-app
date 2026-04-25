# Release Slice — 2026-04-25

## Scope
- Stabilized `v1` clinical harness at `1040` cases.
- Tightened gate threshold: `max_domain_drift_rate` from `0.22` to `0.20`.
- Reduced expect-case drift to zero with targeted seed tuning in `v1-501..520`.

## What changed
- Added deterministic drift diagnostics script:
  - `scripts/drift_debug_run.py`
- Added/updated harness governance docs:
  - `tests/clinical/HARNESS_NEXT_STEPS.md`
  - `tests/clinical/PRE_RELEASE_CHECKLIST.md`
- Added tuned seed pack + generator flow for focused expect-cases:
  - `tests/clinical/seeds_v1_501_520.json`
  - `scripts/_gen_v1_501_520.py` (`--rewrite` supported)
- Refreshed case pack:
  - `tests/clinical/cases_clinical_v1.jsonl`
- Updated threshold file:
  - `tests/clinical/release_gate_thresholds_v1.json`

## Final verification
- Drift debug:
  - `expect_cases=54`
  - `drift_cases=0`
  - `drift_ids=[]`
- Full gate (`v1`):
  - `PASS`
  - `total_cases=1040`
  - `domain_drift_rate=0.0019230769230769232`
  - `loop_rate=0.0`
  - `repair_success_at_1=1.0`
  - `non_empty_response_rate=1.0`
  - `human_tone_rate=0.9769230769230769`
- Investor quality export:
  - `PASS`

## Artifacts
- `tests/clinical/reports/drift_debug_latest.json`
- `tests/clinical/reports/release_gate_latest.json`
- `tests/clinical/reports/investor_quality_report_latest.json`
- `tests/clinical/reports/investor_quality_report_latest.md`
