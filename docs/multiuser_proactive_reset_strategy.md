# 多人主动 Reset 验证原型说明

## 1. 当前策略做了什么

当前实现是一个“验证原型”，不是长期架构模块。它只在 OpenRDW 原有 reset 系统上方增加一个低耦合的主动决策层：

```text
风险计算：MultiUserRiskWorseningModel
策略决策：MultiUserProactiveResetController
策略日志：MultiUserProactiveResetLogger
实际 reset：仍然走 RedirectionManager / resetter 原有公共入口
```

主动策略不会替换 resetter，也不会写新的 reset 动作。若策略决定 reset 某个用户，只调用：

```csharp
RedirectionManager.RequestProactiveReset()
```

随后仍进入 OpenRDW 原有流程：

```text
OnResetTrigger()
resetter.InitializeReset()
resetter.InjectResetting()
OnResetEnd()
```

## 2. 可选策略

`GlobalConfiguration > Proactive Reset > Proactive Reset Strategy` 支持：

```text
PassiveOnly              B0 baseline，只保留原有被动 reset
WorseningHighestRisk     B2，W_H / G_peak 触发，选择当前 individual risk 最高用户
WorseningCounterfactual  B3，W_H / G_peak 触发，用轻量 counterfactual 选择用户
```

B3 当前不是完整 Unity state clone / rollout。它只在预测中把 Reset(i) 近似为“用户 i 短暂停止移动一段时间”，实际 reset 仍由原 resetter 执行。因此第一阶段建议重点比较 B0 与 B2，B3 只作为预留和初步观察。

## 3. 风险与触发

风险计算使用同一套物理空间定义：

```text
GlobalConfiguration.trackingSpacePoints
GlobalConfiguration.obstaclePolygons
```

不会在风险计算里硬编码 10m x 10m。若场景是 Square 且 Square Width = 10，则风险、边界距离和 resetter 都来自同一坐标系。

核心量：

```text
G(t)      当前群体风险
r_i(t)    当前用户 i 的 individual risk
W_H(t)    预测窗口 H 内相对当前 G(t) 的风险恶化累计
G_peak    预测窗口 H 内最高群体风险
```

B2/B3 触发条件：

```text
W_H > theta_W
G_peak > theta_G
当前没有 emergency
当前没有用户正在 reset
候选用户不在 reset / reset cooldown / proactive cooldown / invalid 状态
```

## 4. 关键参数

Inspector 参数位置：

```text
OpenRDW GameObject
Global Configuration (Script)
Proactive Reset
```

常用参数：

```text
proactiveResetStrategy             B0/B2/B3 策略选择
proactiveDecisionDt                主动策略决策间隔
proactiveThetaW                    W_H 触发阈值
proactiveThetaG                    G_peak 触发阈值
proactiveResetCooldown             同一用户主动 reset 冷却
proactiveVelocityHistorySeconds    估计速度的历史窗口
proactivePredictionHorizon         预测窗口 H
proactivePredictionStep            预测采样步长
proactiveResetDurationForPrediction B3 预测中假设 reset 暂停多久
proactiveUserRadius                用户圆盘半径
proactiveSafeBoundaryDistance      边界风险开始上升的距离
proactiveEmergencyBoundaryDistance 主动策略认为 emergency 已发生的边界距离
proactiveSafePairDistance          用户间风险开始上升的圆盘边缘距离
proactiveSeverePairDistance        用户间严重接近距离
```

命令文件现在也支持这些关键字段，例如：

```text
useSimulationTime = true
runInBackstage = true
guaranteeExperimentReproducibility = true
proactiveResetStrategy = PassiveOnly
proactiveThetaW = 0.25
proactiveThetaG = 0.5
proactivePredictionHorizon = 3.0
```

策略名可写：

```text
B0 / baseline / passiveOnly
B2 / worseningHighestRisk / highestRisk
B3 / worseningCounterfactual / counterfactual
```

## 5. 对你这三次实验的核查结论

已检查这三个结果目录：

```text
OpenRDW/Experiment Results/2026-07-16_21-49-57
OpenRDW/Experiment Results/2026-07-16_22-02-25
OpenRDW/Experiment Results/2026-07-16_22-13-07
```

三次都正常结束，`Summary Statistics/Result.csv` 和 `Sampled Metrics` 都生成了，4 个用户的 `EndState` 都是 `Normal`。

但结果不稳定。三次 reset_count 分别为：

```text
第 1 次：55, 55, 53, 54
第 2 次：58, 56, 51, 57
第 3 次：51, 51, 53, 54
```

实验时长也不同：

```text
517.592
517.7139
510.4548
```

因此，若这三次本意是“同一 seed、同一配置重复跑”，当前不能认为稳定可复现。

最可能原因是你截图中的配置：

```text
Movement Controller = Auto Pilot
Run In Backstage = false
Use Simulation Time = false
Target FPS = 20
```

在这种组合下，运动、resetter、统计采样大量依赖真实帧时间 `Time.deltaTime`。不同运行的实际帧耗时不同，会导致轨迹、reset 触发时机和统计结果漂移。要做可复现 smoke test，建议先用：

```text
Movement Controller = Auto Pilot
Run In Backstage = true
Use Simulation Time = true
Target FPS = 固定值，例如 20 或 60
Proactive Reset Strategy = PassiveOnly
```

## 6. 现在日志是否正常

原有日志正常：

```text
Summary Statistics/Result.csv
Sampled Metrics/Result/trialId_0/userId_x/*.csv
Graphs/*.png
Tmp/*.txt
```

但原有日志只能看到总 reset_count，不能区分主动/被动，也不能解释策略为什么触发或未触发。

现在新增主动策略日志，每个 trial 会生成接近最初日志规格的 5 个 CSV：

```text
Experiment Results/{timestamp}/Proactive Reset Logs/trialId_{id}/run_metadata.csv
Experiment Results/{timestamp}/Proactive Reset Logs/trialId_{id}/user_samples.csv
Experiment Results/{timestamp}/Proactive Reset Logs/trialId_{id}/decision_points.csv
Experiment Results/{timestamp}/Proactive Reset Logs/trialId_{id}/reset_events.csv
Experiment Results/{timestamp}/Proactive Reset Logs/trialId_{id}/waypoint_log.csv
```

含义：

```text
run_metadata.csv     seed、策略、空间、H、theta、cooldown 等配置
user_samples.csv     每个决策时钟点的用户位置、速度、individual risk、reset/eligible 状态
decision_points.csv  每次策略决策的 G、W_H、G_peak、eligible users、individual risks、选择原因
reset_events.csv     reset 时间、用户、来源 passive/proactive、是否被现有 reset 入口接受
waypoint_log.csv     每个用户的 waypoint、pathSeedChoice、初始位置和初始朝向
```

B0 `PassiveOnly` 下也会按 `proactiveDecisionDt` 写 `decision_points.csv` 和 `user_samples.csv`，但 `W_H/G_peak` 为空值，且不会产生 proactive reset。若原系统触发被动 reset，`reset_events.csv` 会记录为 `source=passive`。

## 7. 100-run 现在如何做

当前已经补齐 100-run 所需的关键能力：

```text
1. UI 可复现实验由 ExperimentSeedSequence 提供固定 100 个 seed
2. command file 仍可显式配置 seed
3. 每个 ExperimentSetup 会固化自己的 seed，multiCmdFiles 不会被最后一个文件覆盖
4. seed 改变时会重新生成随机 waypoint，保证 waypoint 与 seed 对应
5. B0/B2/B3 可由 command file 配置
6. proactive 参数可由 command file 配置
7. multiCmdFiles 可读取多个 command file 批量跑
8. command file 支持 repeat / trialsForRepeating
9. 每个 trial 有 metadata/user_samples/decision/reset_event/waypoint 日志
```

推荐流程：

```text
1. 先生成 100 个 command file，每个文件只改 seed
2. Unity 中开启 loadFromTxt 和 multiCmdFiles
3. 指向包含 100 个 command file 的目录
4. 先跑 B0 PassiveOnly
5. 确认 100 个 run 均 Normal，且重复同一批 seed 时结果一致
6. 再跑 B2
7. 最后再决定是否比较 B3
```

每个 command file 应固定：

```text
seed 写在 newUser 之前
runInBackstage = true
useSimulationTime = true
targetFPS 固定
trackingSpaceChoice = Square
squareWidth = 10
avatar 数量固定
每个用户 pathSeedChoice 固定
redirector/resetter 固定
initialConfiguration 固定或由同一 seed 生成
```

第一轮建议：

```text
B0: PassiveOnly, seeds 0-99
B2: WorseningHighestRisk, seeds 0-99
暂不正式比较 B3
```

如果只想让同一个配置重复跑 100 次，用两种方式均可：

```text
方式 A：Inspector，固定 seed 序列可复现
loadFromTxt = false
Trials For Repeating = 100
Guarantee Experiment Reproducibility = true
```

```text
方式 B：command file
repeat = 100
seed = 3041
...
end
```

如果想跑 100 个独立 seed，推荐用 `multiCmdFiles` 放 100 个命令文件，每个文件一个 seed。不要用 `repeat=100` 代替独立 seed，因为 `repeat=100` 是同一 seed、同一 setup 的重复复现实验。

也可以直接用 Inspector 做 100 个固定序列 seed：

```text
loadFromTxt = false
Guarantee Experiment Reproducibility = true
Trials For Repeating = 100
```

这样第 1 轮使用 `ExperimentSeedSequence` 提供的第 1 个 seed，第 2 轮使用第 2 个 seed，直到第 100 轮。固定序列由 `ExperimentSeedSequence` 内部给出，不依赖 Inspector 里的 `Random Seed`。下一次用同样配置再跑 100 轮，会得到同一组 seed 和同一组虚拟轨迹；但这 100 轮彼此之间的虚拟轨迹不同。

如果不要求复现：

```text
Guarantee Experiment Reproducibility = false
```

此时每个 trial 会临时生成随机 seed，不保证下一次启动后仍然一致。

## 8. 后续汇报时要说明

建议汇报口径：

```text
B0 是 OpenRDW 原始被动 reset baseline
B2/B3 只增加主动 reset 决策层
主动策略不替换 resetter
所有 reset 执行仍走 OpenRDW 现有 reset manager / resetter 公共入口
风险计算使用场景统一 tracking space，不硬编码房间边界
当前三次手动运行正常完成，但在真实帧时间模式下不可复现
100-run 前必须使用 simulation time / backstage / 外部 seed
新增日志已能记录 seed、策略决策和主动 reset 请求
```
