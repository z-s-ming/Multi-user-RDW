# Ryu-Kim Stage 3

Stage 3 builds on frozen Stage 2 results without modifying Stage 2 predictions,
splits, test samples, or original metrics.

## Completed

- `robustness_analysis/`: paired session-level analysis using existing Stage 2
  LSTM/causal TCN predictions and Baseline v1 Ridge predictions.

## Completed Server Runs

- `high_fms_experiments/`: fixed 10s unidirectional LSTM variants for high-FMS
  underestimation.
- `missingness_experiments/`: fixed Stage 2 LSTM missing-data strategies.

See `final_report.md` for the consolidated interpretation.

## Current Answers From Existing Predictions

- LSTM vs Ridge 3.22% average session-macro MAE improvement is paired-stable
  overall: session MAE difference `-0.1246`, bootstrap 95% CI
  `[-0.1491, -0.1003]`, improved-session fraction `0.706`.
- This does not mean every slice improves. LSTM worsens the 5-10 FMS bin
  (`+0.1865` session MAE difference), while improving 0-5, 10-15, and 15-20.
- Causal TCN improves Ridge on average but remains below the pre-set 3%
  practical threshold from Stage 2.
- Missing-window improvement is not statistically stable from existing Stage 2
  predictions: LSTM vs Ridge missing-window session MAE difference `-0.0081`
  with bootstrap CI crossing zero.

## Final Answers

- LSTM's 3.22% improvement over Ridge is paired-stable overall but modest and
  slice-dependent.
- High-FMS underestimation can be reduced by weighted Huber, but only with clear
  low/mid-FMS and overall performance cost.
- Missing-window performance is not materially improved by causal forward fill
  or time-since-last-observed features.
- Current bottlenecks appear more consistent with label distribution and limited
  dynamic input information than with simple model capacity or missing-value
  handling alone.
