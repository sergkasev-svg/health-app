# Investor Quality Report

- Generated (UTC): `2026-04-25T14:16:30.531659+00:00`
- Overall status: **FAIL**

## Levels

### starter
- Status: **FAIL**
- Cases: `35`
- loop_rate: `0.0000`
- domain_drift_rate: `0.0857`
- redflag_recall: `0.0000`
- repair_success_at_1: `1.0000`
- non_empty_response_rate: `1.0000`
- human_tone_rate: `0.9714`
- Failed metrics: `redflag_recall`

### v1
- Status: **FAIL**
- Cases: `1040`
- loop_rate: `0.0000`
- domain_drift_rate: `0.0019`
- redflag_recall: `0.5625`
- repair_success_at_1: `1.0000`
- non_empty_response_rate: `1.0000`
- human_tone_rate: `0.9635`
- Failed metrics: `redflag_recall`

## Evidence

- Release gate outputs: `tests/clinical/reports/release_gate_latest.json`
- Smoke outputs: `tests/clinical/reports/latest_metrics.json`
