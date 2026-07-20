# 多用户主动 Reset 20 次完整对比实验分析

## 1. 纳入分析的实验

本次分析使用 2026-07-17 生成的三组完整 20-trial 实验：

| 组别 | 策略 | 结果目录 |
|---|---|---|
| B0 | PassiveOnly | `OpenRDW/Experiment Results/2026-07-17_11-41-39` |
| B2 | WorseningHighestRisk | `OpenRDW/Experiment Results/2026-07-17_11-49-11` |
| B3 | WorseningCounterfactual | `OpenRDW/Experiment Results/2026-07-17_11-57-06` |

目录 `2026-07-17_11-41-16` 只有 1 个 trial，不纳入本次分析。

三组实验配置一致：

```text
Trials = 20
run_in_backstage = True
use_simulation_time = True
avatar_num = 4
decision_dt = 0.5
theta_w = 0.25
theta_g = 0.5
proactive_reset_cooldown = 2
```

## 2. 指标定义

本次使用的未来窗口为：

```text
K = 6 个 decision step = 3 秒仿真时间
```

碰撞相关分析使用 `pair_samples.csv` 中的代理指标。原因是 `reset_events.csv` 目前没有区分 passive reset 是由边界触发，还是由用户间碰撞 / 接近触发。

| 指标 | 含义 |
|---|---|
| `pair_risky_count` | 当前 step 中，边缘距离小于 `safe_pair_distance` 的用户对数量 |
| `pair_severe_count` | 当前 step 中，边缘距离小于 `severe_pair_distance` 的用户对数量 |
| `future6_pair_risky_count` | 未来 6 个 decision step 的 `pair_risky_count` 总和 |
| `future6_pair_severe_count` | 未来 6 个 decision step 的 `pair_severe_count` 总和 |
| `future6_min_pair_distance` | 未来 6 个 decision step 内最小用户对边缘距离 |
| `future6_passive_reset_count` | 未来 6 个 decision step 内 passive reset 次数 |

相关性分析以 decision point 为样本。若要判断算法字段与自然风险事件的关系，优先看 B0 `PassiveOnly`，因为 B2/B3 的系统行为已经被这些字段干预过。

## 3. 总体表现：Reset 次数

| 组别 | 总 reset / trial | passive reset / trial | proactive reset / trial |
|---|---:|---:|---:|
| B0 PassiveOnly | 209.40 | 209.40 | 0.00 |
| B2 HighestRisk | 247.45 | 193.75 | 53.70 |
| B3 Counterfactual | 246.15 | 193.75 | 52.40 |

相对 B0 的配对差异：

| 对比 | 总 reset 差值 / trial | 95% CI | passive reset 差值 / trial | proactive reset 差值 / trial |
|---|---:|---:|---:|---:|
| B2 - B0 | +38.05 | [+31.55, +44.55] | -15.65 | +53.70 |
| B3 - B0 | +36.75 | [+27.88, +45.62] | -15.65 | +52.40 |

结论：

```text
B2/B3 都减少了 passive reset，平均每个 trial 少约 15.65 次。
但它们额外引入了约 52-54 次 proactive reset。
因此净效果是总 reset 增加，增幅约 37-38 次 / trial。
```

B3 与 B2 的差异：

| 指标 | B3 - B2 平均差值 / trial | 95% CI |
|---|---:|---:|
| 总 reset | -1.30 | [-8.60, +6.00] |
| passive reset | 0.00 | [-7.94, +7.94] |
| proactive reset | -1.30 | [-4.14, +1.54] |

因此，B2 和 B3 在 reset 总量上几乎没有稳定差异。

## 4. 算法定义的指标是否改善

各组 decision point 平均值：

| 组别 | group_risk | W_H | G_peak | 最小边界距离 | 最小用户间距离 |
|---|---:|---:|---:|---:|---:|
| B0 PassiveOnly | 0.2941 | 0.8180 | 0.6236 | 0.7512 | 1.6026 |
| B2 HighestRisk | 0.2820 | 0.7292 | 0.5821 | 0.7737 | 1.6190 |
| B3 Counterfactual | 0.2884 | 0.7750 | 0.6061 | 0.7650 | 1.6015 |

相对 B0 的配对差异：

| 指标 | B2 - B0 | 95% CI | B3 - B0 | 95% CI |
|---|---:|---:|---:|---:|
| group_risk | -0.0122 | [-0.0218, -0.0025] | -0.0058 | [-0.0143, +0.0028] |
| W_H | -0.0889 | [-0.1022, -0.0755] | -0.0430 | [-0.0599, -0.0260] |
| G_peak | -0.0415 | [-0.0513, -0.0316] | -0.0175 | [-0.0239, -0.0111] |
| 最小边界距离 | +0.0225 | [-0.0022, +0.0471] | +0.0138 | [-0.0018, +0.0293] |
| 最小用户间距离 | +0.0164 | [-0.0665, +0.0994] | -0.0011 | [-0.0670, +0.0648] |

结论：

```text
B2 对算法自身风险字段的改善最明显：
W_H 更低，G_peak 更低，group_risk 也更低。

B3 也降低了 W_H 和 G_peak，但幅度小于 B2。

两组的边界距离都有轻微改善趋势，但 20 次实验下置信区间仍跨 0。
当前最小用户间距离没有稳定改善。
```

## 5. 是否改善了用户间碰撞代理指标

当前 step 的 pair-risk 代理指标：

| 组别 | pair risky count | pair severe count | 出现 risky 的 step 占比 | 出现 severe 的 step 占比 |
|---|---:|---:|---:|---:|
| B0 PassiveOnly | 0.3915 | 0.2373 | 0.3288 | 0.2102 |
| B2 HighestRisk | 0.3579 | 0.2152 | 0.3112 | 0.1951 |
| B3 Counterfactual | 0.3414 | 0.2055 | 0.3014 | 0.1923 |

相对 B0 的配对差异：

| 指标 | B2 - B0 | 95% CI | B3 - B0 | 95% CI |
|---|---:|---:|---:|---:|
| pair risky count | -0.0336 | [-0.0765, +0.0094] | -0.0501 | [-0.0783, -0.0218] |
| pair severe count | -0.0222 | [-0.0517, +0.0073] | -0.0318 | [-0.0551, -0.0086] |
| 出现 risky 的 step 占比 | -0.0175 | [-0.0489, +0.0139] | -0.0273 | [-0.0491, -0.0055] |
| 出现 severe 的 step 占比 | -0.0151 | [-0.0365, +0.0063] | -0.0179 | [-0.0368, +0.0009] |

未来 3 秒窗口的 pair-risk 代理指标：

| 组别 | future6 risky count | future6 severe count | future6 最小用户间距离 |
|---|---:|---:|---:|
| B0 PassiveOnly | 2.3379 | 1.4182 | 0.9497 |
| B2 HighestRisk | 2.1416 | 1.2876 | 1.0181 |
| B3 Counterfactual | 2.0425 | 1.2311 | 0.9730 |

相对 B0 的配对差异：

| 指标 | B2 - B0 | 95% CI | B3 - B0 | 95% CI |
|---|---:|---:|---:|---:|
| future6 risky count | -0.1963 | [-0.4538, +0.0612] | -0.2954 | [-0.4651, -0.1256] |
| future6 severe count | -0.1306 | [-0.3077, +0.0466] | -0.1871 | [-0.3267, -0.0475] |
| future6 最小用户间距离 | +0.0685 | [-0.0110, +0.1479] | +0.0233 | [-0.0351, +0.0817] |

结论：

```text
B3 在 pair risky / severe count 上改善更稳定。
B2 方向也是改善，但 20 次实验下置信区间仍跨 0。

两种策略都没有在平均最小用户间距离上给出足够稳定的改善。
在这批数据里，pair-risk count 比距离均值 / 最小值更敏感。
```

## 6. 算法字段是否真的和未来碰撞风险相关

以下是在 B0 `PassiveOnly` decision points 上计算的 Spearman 相关系数：

| 字段 | future6 risky count | future6 severe count | future6 最小用户间距离 | future6 passive reset |
|---|---:|---:|---:|---:|
| W_H | +0.003 | -0.002 | +0.052 | +0.208 |
| G_peak | +0.221 | +0.241 | -0.189 | +0.056 |
| group_risk | +0.235 | +0.258 | -0.263 | -0.137 |
| min_boundary_distance | +0.083 | +0.063 | -0.070 | +0.126 |
| min_pairwise_distance | -0.527 | -0.470 | +0.574 | -0.050 |
| max_individual_risk | +0.307 | +0.328 | -0.345 | -0.070 |

解释：

```text
W_H 几乎不预测未来用户间 pair-risk。
它和未来 passive reset 的相关性更明显，而不是和未来用户间碰撞代理指标相关。

G_peak 和 group_risk 与未来 pair-risk 有弱到中等相关。

当前 min_pairwise_distance 是最强、最直接的用户间风险信号。
max_individual_risk 对未来 pair-risk 的预测性也强于 W_H / G_peak。
```

因此：

```text
当前 W_H 更像是泛化的风险恶化 / reset 压力指标，
不适合作为用户间碰撞风险的独立触发指标。

如果目标是专门减少用户间碰撞，
触发公式需要更直接地加入 pair distance、pair severe/risky count，
或者未来窗口内 pair distance worsening 项。
```

## 7. 主动 reset 选人分布

| 组别 | user0 | user1 | user2 | user3 |
|---|---:|---:|---:|---:|
| B2 HighestRisk | 734 | 129 | 122 | 89 |
| B3 Counterfactual | 253 | 259 | 276 | 260 |

解释：

```text
B2 明显集中 reset user0。
B3 的选人分布几乎均衡。
```

这说明 B3 的 counterfactual selection 机制确实和 B2 不同，不只是重复 highest-risk 选择。

## 8. 总结

1. 总体 reset 表现：B2/B3 减少了 passive reset，但新增 proactive reset 更多，因此总 reset 增加约 18%。
2. 算法自身指标：B2 对 W_H、G_peak、group_risk 的改善最明显；B3 也改善，但幅度较小。
3. 用户间碰撞代理指标：B3 对 pair risky / severe count 的改善更稳定；B2 有改善趋势，但 20 次下不够稳定。
4. 相关性：W_H 和未来用户间碰撞代理指标几乎无关；G_peak/group_risk 有弱到中等相关；min_pairwise_distance 是最强的碰撞相关信号。
5. 实际建议：如果研究目标是减少用户间碰撞，而不是泛化 reset 压力，主动 reset 触发条件应加入更强的 pair-risk 项。

生成的明细文件：

```text
docs/analysis_outputs/proactive_reset_trial_metrics_2026-07-17_1141_1149_1157.csv
docs/analysis_outputs/proactive_reset_b0_correlations_future6.csv
```
