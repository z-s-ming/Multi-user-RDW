# Ryu-Kim Stage 3 Final Report

Stage 3 reuses the frozen Stage 2 10s split and test samples. It does not modify
Stage 2 predictions, Baseline v1 predictions, split manifests, raw data, or
original metrics.

## 1. Paired Robustness

The Stage 2 LSTM average session-macro MAE improvement over Ridge was 3.22%.
Paired session analysis supports that the overall movement is stable, but not
uniform across the target range.

| comparison | paired session MAE diff | bootstrap 95% CI | improved sessions | Wilcoxon p | effect dz |
| --- | ---: | ---: | ---: | ---: | ---: |
| LSTM - Ridge | -0.1246 | [-0.1491, -0.1003] | 70.6% | ~0 | -0.4807 |
| causal TCN - Ridge | -0.1126 | [-0.1522, -0.0718] | 67.3% | 1.38e-09 | -0.2739 |
| LSTM - causal TCN | -0.0119 | [-0.0403, 0.0167] | 48.4% | 0.738 | -0.0416 |

Interpretation:

- Average metric improvement: LSTM improves Ridge overall.
- Practical threshold: LSTM barely clears the pre-set 3% threshold; causal TCN
  does not.
- Statistical robustness: LSTM and causal TCN both show paired overall
  improvements versus Ridge; LSTM is not robustly better than causal TCN.
- Slice caveat: LSTM improves Ridge in 0-5, 10-15 and 15-20, but worsens 5-10
  with paired session MAE difference +0.1865.
- Missing-window caveat: LSTM vs Ridge on missing windows is not stable
  (difference -0.0081, CI crosses zero).

## 2. High-FMS Experiments

The high-FMS experiment compares fixed 10s unidirectional LSTM variants:

- `standard_huber_lstm`
- `weighted_huber_lstm`
- `multitask_high_fms_lstm`

All bin and auxiliary weights are computed from the current training fold only.

| variant | window MAE | session MAE | group MAE | bias |
| --- | ---: | ---: | ---: | ---: |
| standard_huber_lstm | 3.6585 | 3.6683 | 4.1883 | -0.8047 |
| weighted_huber_lstm | 4.0496 | 4.0578 | 4.7092 | +1.2719 |
| multitask_high_fms_lstm | 3.6512 | 3.6623 | 4.1945 | -0.8113 |

Key FMS-bin results:

| variant | 0-5 MAE | 5-10 MAE | 10-15 MAE | 15-20 MAE | 15-20 bias |
| --- | ---: | ---: | ---: | ---: | ---: |
| standard_huber_lstm | 2.8630 | 2.2834 | 4.0006 | 8.7625 | -8.7625 |
| weighted_huber_lstm | 4.1560 | 3.8764 | 2.5771 | 5.8506 | -5.8486 |
| multitask_high_fms_lstm | 2.8569 | 2.2680 | 4.0246 | 8.7664 | -8.7664 |

Answer: high-FMS underestimation can be reduced by weighted Huber, but not
without obvious cost. Weighted Huber lowers 15-20 MAE substantially
(8.76 -> 5.85) and reduces high-FMS underestimation, but it damages 0-5,
5-10, overall window MAE, session-macro MAE and group-macro MAE. The multitask
auxiliary high-FMS classifier does not meaningfully improve 15-20 performance.

## 3. Missingness Experiments

The missingness experiment compares:

- `zero_mask_lstm`: standardize observed values, fill missing values with 0,
  append missing mask.
- `ffill_mask_lstm`: causal forward fill, append missing mask.
- `ffill_mask_time_lstm`: causal forward fill, append missing mask and
  time-since-last-observed.

| variant | window MAE | session MAE | group MAE | missing-window MAE | peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: |
| zero_mask_lstm | 3.6585 | 3.6683 | 4.1883 | 5.1248 | 222.7 |
| ffill_mask_lstm | 3.6589 | 3.6698 | 4.2159 | 5.1559 | 222.5 |
| ffill_mask_time_lstm | 3.6590 | 3.6706 | 4.2138 | 5.1297 | 311.4 |

Missing block slices:

| variant | no missing MAE | short missing MAE | long missing MAE |
| --- | ---: | ---: | ---: |
| zero_mask_lstm | 3.5881 | 4.8067 | 5.3834 |
| ffill_mask_lstm | 3.5869 | 4.8292 | 5.4214 |
| ffill_mask_time_lstm | 3.5885 | 4.7980 | 5.3995 |

Answer: missing-window performance is not mainly fixed by causal imputation.
Forward fill and time-since-last-observed do not improve overall, session-macro,
group-macro, or missing-window MAE relative to zero-fill + mask. Time-since
features add memory cost without clear gain.

Missing windows are concentrated across a limited set of sessions and raw_pa_id
groups, but not dominated by a single session. The largest raw_pa_id group
contribution is PA115 at about 3.0% of missing windows.

## 4. Main Answers

LSTM relative to Ridge:

- The 3.22% average session-macro MAE improvement is paired-stable overall.
- It is modest and slice-dependent, especially worse in FMS 5-10.
- It should be described as a small, robust average improvement, not a broad
  improvement across all conditions.

High-FMS underestimation:

- Weighted Huber can reduce high-FMS underestimation.
- The reduction comes with clear degradation in low/mid FMS and overall metrics.
- The multitask high-FMS auxiliary head does not solve the high-FMS underestimation.

Missing data:

- Missing windows remain harder than complete windows.
- Causal forward fill and time-since-last-observed do not materially improve
  missing-window performance.

Likely bottleneck:

- The strongest evidence points to label distribution and input information
  limitations rather than simply model capacity.
- High FMS is sparse enough that reweighting changes the tradeoff sharply.
- Missingness contributes to error, but simple causal missing strategies do not
  remove the gap.
- Since inputs exclude static personalization, history of FMS, IDs, condition and
  filenames by design, the six-axis dynamic signal alone may be insufficient for
  uniformly accurate high-FMS prediction.
