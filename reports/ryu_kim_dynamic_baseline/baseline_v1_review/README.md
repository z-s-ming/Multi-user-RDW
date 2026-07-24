# Baseline v1 Review

This review freezes the completed Ryu-Kim dynamic baseline results without modifying original metric or prediction files.

## Verdict

- Split disjoint checks passed: True.
- No evidence of prediction-file reuse was found: ridge and causal_tcn_linear predictions are not bit-identical.
- Ridge vs causal_tcn_linear minimum Pearson r across fold/window pairs: 0.99432197.
- Mean absolute prediction difference across fold/window pairs: 0.111784.
- Maximum absolute prediction difference observed: 3.864296.
- High-FMS 15-20 systematic underestimation detected: True.

## Why Ridge And causal_tcn_linear Are Nearly Identical

`causal_tcn_linear` is not a true nonlinear TCN. It is a Ridge regression over a larger causal lag feature vector.
Its feature vector contains the same 36 summary features used by `ridge_window_stats`, plus 60 causal lag features.
Because the final learner is still linear Ridge and the lag features add little independent signal in this dataset snapshot, predictions are extremely correlated.

## Model Implementation Summary

| model | parameters | input | structure |
| --- | ---: | --- | --- |
| ridge_window_stats | 37 | [batch, 36] summary vector; no raw temporal tensor | linear ridge regression with bias over per-channel mean/std/min/max/first/last |
| causal_tcn_linear | 97 | [batch, 96] lag+summary vector; no nonlinear layers | linear ridge regression with bias over 60 causal lag features plus same 36 summary features |

## Frozen Splits

Frozen split JSON files and SHA256 hashes are stored in `frozen_splits/` and `frozen_split_manifest.csv`.
Future sequence-model experiments must reuse these exact fold assignments.

## Generated Files

- `ridge_vs_tcn_prediction_similarity.csv`
- `model_implementation_review.csv`
- `split_disjoint_review.csv`
- `fold_fms_distribution_and_bin_metrics.csv`
- `high_fms_underestimation.csv`
- `missing_dynamic_window_concentration.csv`
- `README_baseline_v1_fixed_encoding.md`
- `frozen_split_manifest.csv`
