# Stage 3 Robustness Analysis

This analysis uses frozen Stage 2 sequence predictions and Baseline v1 Ridge predictions only.
Negative MAE differences mean the first model has lower paired session MAE.

| comparison | mean session MAE diff | bootstrap 95% CI | improved session fraction | Wilcoxon p | effect dz |
| --- | ---: | ---: | ---: | ---: | ---: |
| lstm_minus_ridge | -0.1246 | [-0.1491, -0.1003] | 0.706 | 0 | -0.4807 |
| causal_tcn_minus_ridge | -0.1126 | [-0.1522, -0.0718] | 0.673 | 1.375e-09 | -0.2739 |
| lstm_minus_causal_tcn | -0.0119 | [-0.0403, 0.0167] | 0.484 | 0.7384 | -0.0416 |

Interpretation separates three claims: average metric movement, the pre-set 3% practical threshold, and paired statistical robustness.
