# Stage 3 High Fms

All runs reuse the Stage 2 frozen 10s split and test samples.

| variant | window MAE | session MAE | group MAE | params | peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: |
| multitask_high_fms_lstm | 3.6512 +/- 0.3681 | 3.6623 +/- 0.3748 | 4.1945 +/- 0.4038 | 5954 | 222.7 |
| standard_huber_lstm | 3.6585 +/- 0.3689 | 3.6683 +/- 0.3748 | 4.1883 +/- 0.4183 | 5921 | 222.7 |
| weighted_huber_lstm | 4.0496 +/- 0.2737 | 4.0578 +/- 0.2816 | 4.7092 +/- 0.5676 | 5921 | 222.5 |
