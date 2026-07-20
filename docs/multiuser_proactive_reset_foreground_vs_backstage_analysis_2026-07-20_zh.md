# 最新非后台三组实验与后台仿真结果对比分析

## 1. 本次要回答的问题

目标是找到最新的三组完整实验，这三组不是后台运行数据，然后按之前同样的分析口径计算：

```text
1. 总体表现：reset 次数
2. 算法定义字段是否改善
3. 算法字段与用户间碰撞代理指标是否相关
4. 结果是否和之前后台仿真数据一致
```

## 2. 纳入分析的最新非后台三组实验

最新的三组完整 20-trial 非后台实验为：

| 组别 | 策略 | 结果目录 | run_in_backstage | use_simulation_time |
|---|---|---|---|---|
| B0 | PassiveOnly | `OpenRDW/Experiment Results/2026-07-17_14-44-54` | False | True |
| B2 | WorseningHighestRisk | `OpenRDW/Experiment Results/2026-07-17_15-53-46` | False | True |
| B3 | WorseningCounterfactual | `OpenRDW/Experiment Results/2026-07-20_09-07-05` | False | True |

说明：

```text
这些实验不是后台运行：run_in_backstage=False。
但它们仍然使用仿真时间：use_simulation_time=True。
因此理论上，如果 seed、路径、策略和配置一致，结果应当可以和后台仿真严格复现。
```

用于对照的后台仿真三组为：

| 组别 | 策略 | 结果目录 | run_in_backstage | use_simulation_time |
|---|---|---|---|---|
| B0 | PassiveOnly | `OpenRDW/Experiment Results/2026-07-17_11-41-39` | True | True |
| B2 | WorseningHighestRisk | `OpenRDW/Experiment Results/2026-07-17_11-49-11` | True | True |
| B3 | WorseningCounterfactual | `OpenRDW/Experiment Results/2026-07-17_11-57-06` | True | True |

## 3. 复现性检查

最新非后台三组和之前后台三组的关键条件一致：

```text
Trials = 20
random_seed = 918273
virtual_path_generator_seed = 918273
guarantee_experiment_reproducibility = True
movement_controller = AutoPilot
use_simulation_time = True
target_fps = 20
avatar_num = 4
tracking_space = Square
square_width = 10
decision_dt = 0.5
theta_w = 0.25
theta_g = 0.5
proactive_reset_cooldown = 2
```

抽样哈希检查也显示核心日志逐字节一致：

| 对比 | 文件 | trial | SHA256 是否一致 |
|---|---|---:|---|
| B0 后台 vs 非后台 | `decision_points.csv` | 0 | 是 |
| B2 后台 vs 非后台 | `reset_events.csv` | 7 | 是 |
| B3 后台 vs 非后台 | `pair_samples.csv` | 19 | 是 |

因此，本次非后台实验不是“近似一致”，而是在日志层面与之前后台仿真结果一致。

## 4. 最新非后台三组的总体 reset 表现

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
与之前后台仿真结论完全一致：
B2/B3 都减少 passive reset，但新增 proactive reset 更多。
所以总 reset 数量上升，平均每 trial 多约 37-38 次。
```

B3 与 B2 的差异：

| 指标 | B3 - B2 平均差值 / trial | 95% CI |
|---|---:|---:|
| 总 reset | -1.30 | [-8.60, +6.00] |
| passive reset | 0.00 | [-7.94, +7.94] |
| proactive reset | -1.30 | [-4.14, +1.54] |

因此，B2 和 B3 在 reset 总量上仍然没有稳定差异。

## 5. 算法定义字段是否改善

最新非后台三组的 decision point 平均值：

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

结论也与后台仿真一致：

```text
B2 对算法自身指标改善最明显：
W_H、G_peak、group_risk 都下降。

B3 也改善 W_H 和 G_peak，但幅度小于 B2。

边界距离只有轻微改善趋势。
最小用户间距离没有稳定改善。
```

## 6. 用户间碰撞代理指标是否改善

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

结论仍与后台仿真一致：

```text
B3 对 pair risky / severe count 的改善更稳定。
B2 的方向也是改善，但 20 次实验下置信区间跨 0。

两组都没有在 future6 最小用户间距离上给出稳定改善。
```

## 7. 算法字段与未来碰撞风险的相关性

在 B0 PassiveOnly 非后台实验上计算 Spearman 相关性：

| 字段 | future6 risky count | future6 severe count | future6 最小用户间距离 | future6 passive reset |
|---|---:|---:|---:|---:|
| W_H | +0.003 | -0.002 | +0.052 | +0.208 |
| G_peak | +0.221 | +0.241 | -0.189 | +0.056 |
| group_risk | +0.235 | +0.258 | -0.263 | -0.137 |
| min_boundary_distance | +0.083 | +0.063 | -0.070 | +0.126 |
| min_pairwise_distance | -0.527 | -0.470 | +0.574 | -0.050 |
| max_individual_risk | +0.307 | +0.328 | -0.345 | -0.070 |

这与之前后台仿真数据完全一致。

解释保持不变：

```text
W_H 几乎不预测未来用户间 pair-risk。
G_peak 和 group_risk 与未来 pair-risk 有弱到中等相关。
min_pairwise_distance 是最强、最直接的用户间风险信号。
max_individual_risk 也比 W_H / G_peak 更能反映未来 pair-risk。
```

## 8. 主动 reset 选人分布

最新非后台三组中的 proactive reset 选人分布：

| 组别 | user0 | user1 | user2 | user3 |
|---|---:|---:|---:|---:|
| B2 HighestRisk | 734 | 129 | 122 | 89 |
| B3 Counterfactual | 253 | 259 | 276 | 260 |

与后台仿真一致：

```text
B2 明显集中 reset user0。
B3 选人几乎均衡。
```

## 9. 与后台仿真数据是否一致

所有主要聚合指标的差异均为：

```text
foreground_simtime - backstage_simtime = 0
```

包括：

```text
reset 次数
passive / proactive reset 分解
W_H
G_peak
group_risk
边界距离
用户间距离
pair risky / severe count
future6 pair-risk 指标
B0 相关性结果
proactive reset 选人分布
```

因此可以判断：

```text
在 use_simulation_time=True 且 seed / waypoint / 策略配置一致时，
run_in_backstage=True 和 run_in_backstage=False 不改变本批实验结果。

这三组最新非后台实验与之前后台仿真实验结论完全一致。
```

## 10. 最终结论

1. 最新三组非后台实验已经找到，并且都是完整 20-trial 数据。
2. 它们不是后台运行数据，但仍使用 simulation time。
3. 统计结果与之前后台仿真三组完全一致。
4. 原结论不需要修改：
   B2/B3 减少 passive reset，但总 reset 增加；B2 更明显改善算法自身风险字段；B3 更稳定改善 pair-risk count；W_H 与未来用户间碰撞代理指标几乎无关。
5. 如果后续目标是减少用户间碰撞，仍建议把触发条件从主要依赖 W_H，改为更直接纳入 pair-risk / future pair-distance worsening。

生成的明细文件：

```text
docs/analysis_outputs/proactive_reset_trial_metrics_foreground_simtime_2026-07-17_1444_1553_2026-07-20_0907.csv
docs/analysis_outputs/proactive_reset_b0_correlations_foreground_simtime_future6.csv
docs/analysis_outputs/proactive_reset_foreground_group_means.csv
```
