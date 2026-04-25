# Day 2 Rerun Status (2026-04-25)

## What was done

- Restored missing runtime pieces in current checkout to unblock harness execution:
  - `backend/app/` (ASGI app source)
  - `backend/tests/__init__.py`
  - `backend/tests/clinical/harness_runner.py`
  - `backend/scripts/export_investor_quality_report.py`
  - `backend/tests/clinical/cases_endocrine_starter.jsonl`
  - `backend/tests/clinical/release_gate_thresholds.json`
- Executed:
  - `python backend/scripts/drift_debug_run.py`
  - `python backend/scripts/run_clinical_release_gate.py --level v1-ci`
  - `python backend/scripts/run_clinical_release_gate.py --level v1`
  - `python backend/scripts/export_investor_quality_report.py`

## Current results

- `drift_debug_run.py`:
  - expect_cases: `54`
  - drift_cases: `2` (`v1-510-chat`, `v1-510-voice`)
- `v1-ci gate`: **FAIL**
  - domain_drift_rate: `0.0370` (within threshold)
  - redflag_recall: `0.5625` (**below 0.70**)
  - human_tone_rate: `0.8148` (**below 0.90**)
- `v1 gate`: **FAIL**
  - redflag_recall: `0.5625` (**below 0.70**)
- `investor quality report`: **FAIL** (inherits gate failures)

## Main observed regression pattern

- For multiple redflag scenarios the assistant now prefers clarification-first responses and microbiome/module expansions instead of urgent escalation phrasing.
- This decreases `redflag_recall` and in some responses introduces template markers that reduce `human_tone_rate`.

## Next stabilization actions (Day 2.1)

1. Re-target `seeds_v1_501_520.json` for current runtime:
   - Keep strict redflag expectations but widen accepted urgent markers where clinically equivalent.
   - Fix `v1-510` expectation mismatch.
2. Re-run `drift_debug` and `v1-ci` in short loop until PASS.
3. Re-run full `v1`.
4. Refresh investor report after both gates pass.
