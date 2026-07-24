# Stage 3 Missingness

All runs reuse the Stage 2 frozen 10s split and test samples.

| variant | window MAE | session MAE | group MAE | params | peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: |
| ffill_mask_lstm | 3.6589 +/- 0.3663 | 3.6698 +/- 0.3729 | 4.2159 +/- 0.4178 | 5921 | 222.5 |
| ffill_mask_time_lstm | 3.6590 +/- 0.3634 | 3.6706 +/- 0.3703 | 4.2138 +/- 0.4135 | 6689 | 311.4 |
| zero_mask_lstm | 3.6585 +/- 0.3689 | 3.6683 +/- 0.3748 | 4.1883 +/- 0.4183 | 5921 | 222.7 |
