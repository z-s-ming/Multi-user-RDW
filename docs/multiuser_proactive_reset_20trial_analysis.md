# 多人主动 Reset 20 次小规模实验分析

## 1. 实验目录

本次纳入分析的三组完整实验为：

| 组别 | 策略 | 结果目录 |
|---|---|---|
| B0 | PassiveOnly | `OpenRDW/Experiment Results/2026-07-17_09-56-55` |
| B2 | WorseningHighestRisk | `OpenRDW/Experiment Results/2026-07-17_10-08-53` |
| B3 | WorseningCounterfactual | `OpenRDW/Experiment Results/2026-07-17_10-19-29` |

另有目录：

```text
OpenRDW/Experiment Results/2026-07-17_10-32-13
```

该目录只有 7 个 trial，且没有生成 summary，因此本次分析排除。

## 2. 可比性检查

三组完整实验均满足：

```text
Trials = 20
Avatar Num = 4
Movement Controller = AutoPilot
Run In Backstage = True
Use Simulation Time = True
Target FPS = 20
Guarantee Experiment Reproducibility = True
Tracking Space = Square
Square Width = 10
PathSeedChoice = RandomTurn
Redirector = DynamicAPF
Resetter = APF
```

逐 trial 检查结果：

```text
seed 对齐：是
waypoint_log.csv 对齐：是
```

因此这三组可以作为同一批虚拟轨迹下的策略对比。

## 3. 核心结果

| 组别 | Trial 数 | 平均总 reset/trial | 最小 | 最大 | 平均每用户 reset | 平均边界距离 | 平均中心距离 |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 PassiveOnly | 20 | 209.40 | 182 | 231 | 52.35 | 2.6906 | 3.6272 |
| B2 HighestRisk | 20 | 247.45 | 229 | 271 | 61.86 | 2.7043 | 3.5603 |
| B3 Counterfactual | 20 | 246.15 | 227 | 262 | 61.54 | 2.7348 | 3.5287 |

相对 B0：

| 对比 | 平均 reset 差值/trial | 标准差 | 最小差值 | 最大差值 |
|---|---:|---:|---:|---:|
| B2 - B0 | +38.05 | 14.82 | +14 | +65 |
| B3 - B0 | +36.75 | 20.24 | +5 | +73 |

结论：

```text
B2/B3 都明显改变了行为。
B2/B3 都比 B0 增加 reset 次数。
增幅大约为 18% 左右。
```

## 4. B2 与 B3 的差异

B3 相对 B2 的配对差异：

| 指标 | B3 - B2 平均差 | 95% CI 下界 | 95% CI 上界 | 说明 |
|---|---:|---:|---:|---|
| 总 reset/trial | -1.30 | -9.09 | +6.49 | 差异很小 |
| 平均边界距离 | +0.0305 | -0.0269 | +0.0880 | 方向略好，但 20 次下不稳 |

当前 20 次数据下，不能说 B3 在核心指标上已经显著优于 B2。

## 5. 主动 Reset 触发与选人

主动 reset 事件数量：

| 组别 | 被动 reset 事件 | 主动 reset 事件 | 平均主动 reset/trial |
|---|---:|---:|---:|
| B0 | 4188 | 0 | 0 |
| B2 | 3875 | 1074 | 53.70 |
| B3 | 3875 | 1048 | 52.40 |

B2/B3 的主动 reset 次数接近。

但选人分布差异明显：

| 组别 | user0 | user1 | user2 | user3 |
|---|---:|---:|---:|---:|
| B2 HighestRisk | 734 | 129 | 122 | 89 |
| B3 Counterfactual | 253 | 259 | 276 | 260 |

解释：

```text
B2 使用当前 highest individual risk，明显偏向 user0。
B3 使用 counterfactual benefit，选人分布非常均衡。
```

这说明 B3 的“选谁 reset”机制确实和 B2 不同，不只是重复 B2 的选择。

## 6. 当前判断

可以确认：

```text
1. seed / waypoint / 日志 / 批量 trial 管线可用。
2. B0/B2/B3 三组实验是可比的。
3. B2/B3 都会触发主动 reset。
4. B2/B3 相比 B0 明显增加 reset 次数。
5. B3 相比 B2 的选人更均衡。
```

暂时不能确认：

```text
1. B3 是否显著优于 B2。
2. B2/B3 增加的 reset 次数是否值得。
3. 当前 thetaW/thetaG/cooldown 是否过于激进。
```

## 7. 是否需要跑 100 次

如果目标只是验证实现与日志是否正常：

```text
20 次已经足够。
```

如果目标是汇报 B2/B3 的策略优劣：

```text
建议每组跑 100 次。
```

原因：

```text
B2 和 B3 在 reset 次数、边界距离上的差异很小。
20 次下 B3 的边界距离方向略好，但置信区间仍跨 0。
需要 100 次降低方差，才能判断 B3 是否真的优于 B2。
```

不过，不建议直接盲目扩大到 100。当前主动策略 reset 增幅较大，建议先确定实验目标：

| 目标 | 建议 |
|---|---|
| 验证主动 reset 是否改变行为 | 当前 20 次足够 |
| 比较 B2 vs B3 谁更好 | 跑 100 次 |
| 希望减少 reset 增幅 | 先调高 `thetaW/thetaG` 或增加 cooldown，再跑 20 次 smoke test |

## 8. 下一步建议

建议优先做一轮参数收敛，而不是马上跑 100：

```text
1. 保持 B0 不变。
2. 对 B2/B3 提高 thetaW 或 thetaG，或增加 proactiveResetCooldown。
3. 每组先跑 20 次。
4. 观察 reset 增幅是否下降，同时边界/接近风险是否仍改善。
5. 找到更合理参数后，再跑 100 次正式对比。
```

当前初步建议：

```text
如果目标是少 reset：提高 thetaW/thetaG。
如果目标是避免连续打断同一用户：增加 proactiveResetCooldown。
如果目标是比较选人公平性：B3 已经明显优于 B2。
```
