# Ryu-Kim Stage 4 Final Report

Stage 4 was run on top of frozen Stage 1-3 artifacts. It does not modify Stage
1-3 predictions, split manifests, test samples, original metrics, or raw data.

The downloaded server outputs were found under `shared/data/exports/stage4/stage4/`.
The summaries below aggregate those outputs and compare them with the frozen
Stage 1 Ridge and Stage 2 LSTM references.

## Baseline References

| reference | window MAE | session MAE | group MAE |
| --- | ---: | ---: | ---: |
| Stage 1 Ridge 10s | 3.8586 | 3.8685 | 4.3366 |
| Stage 2 LSTM 10s | 3.7339 | 3.7441 | 4.2777 |

## 1. FMS Label Diagnostics

The FMS label process is highly stepped and event-driven.

- Sessions: 428.
- FMS update events: 15056.
- Up / down updates: 9268 / 5788.
- High-FMS events: 2714.
- Median stair duration: 1.053s.
- 95th percentile stair duration by fold is roughly 25-32s; max duration is
  166.037s.
- Median absolute update magnitude is 1.0; max is 11.0.

Implication: current-FMS regression mixes long flat intervals with sparse update
events. Update-adjacent windows are harder than flat windows.

## 2. History Length

Full effective-window comparison:

| history | windows | MAE | RMSE | bias |
| ---: | ---: | ---: | ---: | ---: |
| 10s | 192219 | 3.6977 | 4.7812 | -0.8514 |
| 20s | 184343 | 3.7736 | 4.8228 | -0.8411 |
| 40s | 168215 | 3.8761 | 4.8794 | -0.6023 |
| 60s | 152325 | 3.9914 | 5.0223 | -0.6802 |
| 120s | 101961 | 4.2928 | 5.3149 | -0.9769 |

Common-anchor comparison on the 98059 test anchors available to every history:

| history | common-anchor MAE | common-anchor RMSE | bias |
| ---: | ---: | ---: | ---: |
| 10s | 4.2510 | 5.2491 | -0.9446 |
| 20s | 4.2492 | 5.2333 | -0.9174 |
| 40s | 4.2286 | 5.1519 | -0.4648 |
| 60s | 4.2757 | 5.2332 | -0.5735 |
| 120s | 4.2831 | 5.2861 | -0.9552 |

Answer: longer history is not stably better than 10s. On all effective windows,
10s is best. On common anchors, 40s is slightly best, but the gain over 10s is
only about 0.022 MAE, while 60s and 120s degrade. This does not support a robust
long-history advantage.

## 3. Causal Cumulative Motion Dose

| variant | window MAE | session MAE | group MAE |
| --- | ---: | ---: | ---: |
| local_sequence | 3.6977 | 3.7105 | 4.2885 |
| cumulative_dose | 3.7540 | 3.7598 | 4.3333 |
| window_stats | 3.7049 | 3.7162 | 4.2736 |
| sequence_plus_dose | 3.6985 | 3.7042 | 4.2511 |

Answer: causal cumulative dose is informative but not more informative than the
local sequence. Dose-only is worse than local sequence. Adding dose to sequence
barely changes window MAE and gives only a tiny session/group macro improvement.
The evidence supports dose features as a small regularizing/context feature, not
as a replacement for local dynamics.

## 4. Session-Recorded Static Susceptibility Features

All 428 sessions passed within-session static consistency checks for age, gender
and MSSQ. These fields are interpreted only as session-recorded static
susceptibility features, not confirmed participant identity or personalized
identity features.

| variant | window MAE | session MAE | group MAE |
| --- | ---: | ---: | ---: |
| static_only | 4.2322 | 4.2502 | 4.7311 |
| dynamic | 3.6832 | 3.6942 | 4.2548 |
| cumulative_dose | 3.7490 | 3.7551 | 4.3095 |
| static_dose | 3.6296 | 3.6280 | 4.2472 |
| static_dynamic | 3.5616 | 3.5735 | 4.0899 |
| static_dynamic_dose | 3.5954 | 3.6004 | 4.1953 |

Answer: static susceptibility does explain meaningful cross-session variation,
but not by itself. Static-only is weak, worse than dynamic-only. However,
static+dynamic is the best Stage 4 model and improves over dynamic-only by about
0.121 session MAE. Adding dose on top of static+dynamic does not help.

## 5. Update Events, Future Change and Multitask Model

FMS prediction is harder near update events:

| variant | flat-window MAE | update-window MAE |
| --- | ---: | ---: |
| dynamic | 3.6597 | 4.1624 |
| multitask | 3.6787 | 4.1568 |

Auxiliary task metrics for the multitask model:

| auxiliary target | mean |
| --- | ---: |
| update-event AUPRC | 0.0995 |
| update-event F1 | 0.1502 |
| update-event recall | 0.3378 |
| future 5s delta MAE | 0.9200 |
| future 10s delta MAE | 1.4308 |

Current-FMS regression comparison:

| variant | window MAE | session MAE | group MAE |
| --- | ---: | ---: | ---: |
| dynamic | 3.6977 | 3.7105 | 4.2885 |
| multitask | 3.7149 | 3.7221 | 4.3065 |

Answer: update events and future changes have weak predictability from the
available causal dynamic inputs. The multitask model very slightly improves
update-window MAE but worsens flat-window and global metrics. It does not produce
a meaningful architecture gain over the existing small LSTM-style dynamic model.

## Final Answers

Longer history:

- No stable advantage over 10s.
- 40s is slightly better only on common anchors, by a very small margin.
- 60s and 120s are worse.

Causal cumulative motion dose:

- Dose-only is weaker than local sequence.
- Sequence+dose is nearly tied with sequence and only marginally better on
  session/group macro metrics.
- Dose is a small supplemental context, not the main missing signal.

Session-recorded static susceptibility:

- Static-only is insufficient.
- Static+dynamic is the clearest Stage 4 improvement and likely captures
  cross-session susceptibility variance.
- This must not be described as confirmed participant personalization.

Update events and future change:

- Update-adjacent windows are harder.
- Event prediction is weak (AUPRC about 0.10, F1 about 0.15).
- Future FMS deltas have nontrivial error and do not translate into better
  current-FMS prediction under the tested multitask setup.

Multiscale multitask model:

- No. It does not exceed the dynamic baseline; it slightly worsens global,
  session-macro and group-macro metrics.

Likely data/model ceiling:

- The strongest new signal is static susceptibility when combined with dynamic
  input.
- Longer raw history, cumulative dose and multitask event targets do not unlock a
  large dynamic-only gain.
- Current bottlenecks are likely sparse stepped labels, weakly predictable update
  events and missing/non-observed susceptibility information, more than simple
  short-horizon model architecture capacity.
