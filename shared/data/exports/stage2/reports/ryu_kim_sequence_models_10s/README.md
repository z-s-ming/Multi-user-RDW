# Ryu-Kim 10s Sequence Models

Post-run review of true nonlinear 10-second sequence models using the Baseline v1 frozen raw_pa_id-group-disjoint split.

## Scope

- Inputs: six dynamic channels plus six missing masks only.
- Excluded inputs: FMS history, age, gender, MSSQ, raw_pa_id, session_uid, condition, filename, and future frames.
- Static personalization: false.
- Cross-dataset transfer or Unity real-time deployment claim: false.
- Frozen split source: reports/ryu_kim_dynamic_baseline/baseline_v1_review/frozen_splits/splits_10s.json.

## Summary

- Baseline v1 Ridge 10s session-macro MAE: 3.8685.
- Baseline v1 Ridge 10s window MAE: 3.8586.

| model | window MAE | session MAE | group MAE | session MAE improvement vs Ridge | paired abs-error diff vs Ridge | params | train time total | peak GPU MB | latency ms/window |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| causal_tcn | 3.7474 +/- 0.2821 | 3.7558 +/- 0.2841 | 4.2607 +/- 0.3426 | 2.91% | -0.1112 | 17153 | 174.3s | 205.3 | 0.0050 |
| lstm | 3.7339 +/- 0.2599 | 3.7441 +/- 0.2654 | 4.2777 +/- 0.2883 | 3.22% | -0.1246 | 5921 | 103.3s | 222.1 | 0.0019 |

## Interpretation

- causal_tcn: improvement is below 3%; do not treat this as a meaningful gain over Ridge.
- lstm: session-macro MAE improves over Ridge by 3.22% on the same frozen split.

High-FMS bins should still be inspected separately; sequence models remain systematically biased downward in the 15-20 range.
