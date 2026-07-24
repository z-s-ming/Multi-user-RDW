# Ryu-Kim Dynamic Baseline

This is a limited controlled dynamic-feature baseline. It does not train with static personal information and does not claim cross-dataset or Unity real-time deployment performance.

## Required Declarations

- Current public repository snapshot contains 428 sessions.
- True participant identity is still unconfirmed.
- Current results are an identifier-group-disjoint dynamic baseline using a raw_pa_id-group-disjoint split.
- Static personalization is not included.
- Results do not represent cross-dataset transfer or Unity real-time deployment performance.

## Mean ± Std Across Folds

| window | model | window MAE | window RMSE | window R2 | session MAE | group MAE | train s | latency ms/window | params |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10s | causal_tcn_linear | 3.8562 ± 0.2110 | 4.7506 ± 0.3797 | 0.1934 ± 0.0281 | 3.8662 ± 0.2171 | 4.3347 ± 0.3124 | 129.6125 | 0.0052 | 97 |
| 10s | mean_fms | 4.3762 ± 0.2166 | 5.3710 ± 0.3652 | -0.0323 ± 0.0220 | 4.3889 ± 0.2211 | 4.7878 ± 0.4962 | 0.0024 | 0.0000 | 1 |
| 10s | ridge_window_stats | 3.8586 ± 0.2108 | 4.7527 ± 0.3795 | 0.1927 ± 0.0279 | 3.8685 ± 0.2169 | 4.3366 ± 0.3135 | 20.9758 | 0.0023 | 37 |
| 30s | causal_tcn_linear | 3.8923 ± 0.2709 | 4.7782 ± 0.3883 | 0.1660 ± 0.0447 | 3.8944 ± 0.2792 | 4.3642 ± 0.2775 | 119.6744 | 0.0052 | 97 |
| 30s | mean_fms | 4.3304 ± 0.2558 | 5.2907 ± 0.3892 | -0.0225 ± 0.0216 | 4.3359 ± 0.2746 | 4.7138 ± 0.4115 | 0.0022 | 0.0000 | 1 |
| 30s | ridge_window_stats | 3.8925 ± 0.2707 | 4.7785 ± 0.3884 | 0.1658 ± 0.0449 | 3.8947 ± 0.2791 | 4.3643 ± 0.2781 | 19.5047 | 0.0023 | 37 |
| 60s | causal_tcn_linear | 4.0390 ± 0.4234 | 4.9192 ± 0.5746 | 0.0960 ± 0.0619 | 4.0360 ± 0.4390 | 4.4690 ± 0.4802 | 103.6054 | 0.0052 | 97 |
| 60s | mean_fms | 4.3957 ± 0.3812 | 5.3215 ± 0.5459 | -0.0602 ± 0.0710 | 4.3936 ± 0.4021 | 4.7659 ± 0.4618 | 0.0019 | 0.0000 | 1 |
| 60s | ridge_window_stats | 4.0408 ± 0.4209 | 4.9215 ± 0.5742 | 0.0952 ± 0.0612 | 4.0377 ± 0.4362 | 4.4693 ± 0.4810 | 16.8204 | 0.0023 | 37 |
