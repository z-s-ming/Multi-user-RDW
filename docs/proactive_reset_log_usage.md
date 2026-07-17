# Proactive Reset 日志使用说明

## 1. 日志目录结构

每次运行会在 OpenRDW 原有结果目录下生成日志：

```text
OpenRDW/Experiment Results/{timestamp}/
```

原生 OpenRDW 日志包括：

```text
Summary Statistics/Result.csv
Sampled Metrics/Result/trialId_x/userId_y/*.csv
Graphs/*.png
Tmp/*.txt
```

新增主动 reset / shadow policy 日志位于：

```text
OpenRDW/Experiment Results/{timestamp}/Proactive Reset Logs/trialId_{id}/
```

每个 trial 一个子目录，包含：

```text
run_metadata.csv
decision_points.csv
user_samples.csv
pair_samples.csv
reset_events.csv
waypoint_log.csv
```

## 2. 推荐对齐方式

推荐以 `decision_points.csv` 作为主表。

主键：

```text
trial_id + decision_index
```

辅助对齐字段：

```text
trial_id + time
```

各文件对齐方式：

| 文件 | 粒度 | 对齐方式 |
|---|---|---|
| `decision_points.csv` | 每个 decision step 一行 | 主表 |
| `user_samples.csv` | 每个 decision step、每个用户一行 | 用 `time` 对齐 |
| `pair_samples.csv` | 每个 decision step、每对用户一行 | 用 `time` 对齐 |
| `reset_events.csv` | 每次 reset 一行 | 将 reset time 映射到最近 decision step |
| `waypoint_log.csv` | trial 静态轨迹定义 | 用 `trial_id` 对齐 |
| `run_metadata.csv` | trial 配置 | 用 `trial_id` 对齐 |

注意：

```text
不要用 execute_duration 做仿真分析。
execute_duration 是真实运行耗时，只反映后台仿真跑得快慢。
```

## 3. run_metadata.csv

记录当前 trial 的配置。

常用字段：

```text
trial_id
random_seed
guarantee_experiment_reproducibility
virtual_path_generator_seed
strategy
movement_controller
run_in_backstage
use_simulation_time
target_fps
avatar_num
tracking_space
square_width
decision_dt
theta_w
theta_g
prediction_horizon
prediction_step
velocity_history_seconds
proactive_reset_cooldown
safe_boundary_distance
emergency_boundary_distance
safe_pair_distance
severe_pair_distance
```

用途：

```text
1. 检查实验配置是否一致。
2. 检查三组策略是否使用相同 seed 序列。
3. 检查是否使用后台仿真和仿真时间。
```

## 4. decision_points.csv

每个 decision step 一行，是算法分析主表。

字段：

```text
decision_index
time
strategy
group_risk
w_h
g_peak
min_boundary_distance
min_pairwise_distance
emergency
max_individual_risk_user_id
max_individual_risk
triggered
selected_user_id
selection_reason
eligible_users
individual_risks
```

字段含义：

| 字段 | 含义 |
|---|---|
| `decision_index` | 第几个策略采样点 |
| `time` | 仿真时间，不是现实执行时间 |
| `group_risk` | 当前群体风险 |
| `w_h` | 预测窗口内风险恶化累计 |
| `g_peak` | 预测窗口内最高群体风险 |
| `min_boundary_distance` | 当前最近边界距离 |
| `min_pairwise_distance` | 当前最近用户间圆盘边缘距离 |
| `emergency` | 当前是否进入 emergency 状态 |
| `max_individual_risk_user_id` | 当前 individual risk 最高用户 |
| `max_individual_risk` | 当前最高 individual risk |
| `triggered` | 当前 step 是否触发主动 reset 条件 |
| `selected_user_id` | 若触发，选择 reset 的用户 |
| `selection_reason` | 策略状态或选择原因 |
| `eligible_users` | 当前可被主动 reset 的用户 |
| `individual_risks` | 每个用户的 individual risk |

PassiveOnly 下也会计算 shadow policy 字段：

```text
w_h
g_peak
group_risk
min_boundary_distance
min_pairwise_distance
```

但不会执行 proactive reset：

```text
triggered = 0
selection_reason = passive_shadow_no_action
```

因此，若要分析算法字段和自然发生事件的关系，应优先使用 PassiveOnly 数据。

## 5. user_samples.csv

每个 decision step、每个用户一行。

字段：

```text
time
user_id
pos_x
pos_y
vel_x
vel_y
individual_risk
is_resetting
is_eligible
```

用途：

```text
1. 重建每个用户的位置轨迹。
2. 计算用户速度和累计真实行走距离。
3. 分析某个用户是否经常成为高风险用户。
4. 对齐 decision_points 中的 individual risk。
```

可派生字段：

```text
step_distance_i = distance(pos_i(t), pos_i(t-1))
cumulative_distance_i
speed_i = step_distance_i / delta_sim_time
```

## 6. pair_samples.csv

每个 decision step、每对用户一行。

字段：

```text
time
user_a
user_b
pair_edge_distance
pair_center_distance
is_pair_severe
is_pair_risky
```

字段含义：

```text
pair_center_distance = 两个用户中心距离
pair_edge_distance = pair_center_distance - 2 * user_radius
is_pair_risky = pair_edge_distance < safe_pair_distance
is_pair_severe = pair_edge_distance < severe_pair_distance
```

用途：

```text
1. 分析用户间接近或碰撞风险。
2. 构造 pair collision proxy。
3. 计算未来窗口内用户间接近密度。
```

常用聚合：

```text
min_pair_distance_at_step
pair_risky_count_at_step
pair_severe_count_at_step
future_K_steps_min_pair_distance
future_K_steps_pair_risky_count
future_K_steps_pair_severe_count
```

## 7. reset_events.csv

每次 reset 事件一行。

字段：

```text
reset_index
time
user_id
source
accepted
reason
```

字段含义：

```text
source = passive 或 proactive
accepted = 是否进入现有 resetter 执行流程
```

对齐方法：

```text
将 reset_events.time 映射到 decision_points 中最近的 decision step。
推荐使用 time <= reset_time 的最近 decision_index。
```

可派生字段：

```text
future_K_steps_reset_count
future_K_steps_passive_reset_count
future_K_steps_proactive_reset_count
reset_burst_count
```

注意：

```text
目前 passive reset 没有区分边界触发还是用户间碰撞触发。
如果要分析用户间碰撞，应结合 pair_samples.csv。
```

## 8. waypoint_log.csv

每个用户的虚拟 waypoint 定义。

字段：

```text
user_id
path_seed_choice
waypoint_index
x
y
initial_x
initial_y
initial_forward_x
initial_forward_y
```

用途：

```text
1. 检查不同策略组是否使用相同虚拟轨迹。
2. 检查 seed 是否复现。
3. 做 trial 间可比性验证。
```

常用检查：

```text
同一 trial_id 下，不同策略组的 waypoint_log.csv 哈希应一致。
```

## 9. 推荐分析窗口

后台仿真时，不应使用真实运行秒数。

推荐窗口定义：

```text
future K decision steps
```

例如：

```text
decision_dt = 0.5
K = 6
=> 未来 3 秒仿真窗口
```

推荐派生指标：

```text
future_6_steps_reset_count
future_6_steps_passive_reset_count
future_6_steps_pair_risky_count
future_6_steps_pair_severe_count
future_6_steps_min_pair_distance
```

也可以使用距离窗口：

```text
future_2m_pair_severe_count
future_2m_reset_count
```

距离窗口需要从 `user_samples.csv` 重建累计行走距离。

## 10. 推荐分析问题

### 10.1 W_H 是否预测自然 reset

使用 PassiveOnly 数据：

```text
X = w_h
Y = future_K_steps_passive_reset_count
```

推荐统计：

```text
Spearman correlation
high-W_H quartile vs low-W_H quartile
```

### 10.2 W_H 是否预测用户间碰撞风险

使用 PassiveOnly 数据：

```text
X = w_h
Y = future_K_steps_pair_severe_count
Y = future_K_steps_min_pair_distance
```

如果相关性弱，说明当前 `W_H` 不适合作为用户间碰撞风险指标。

### 10.3 G_peak / group_risk 是否更适合用户间风险

比较：

```text
w_h
g_peak
group_risk
min_pairwise_distance
```

对以下结果的相关性：

```text
future_K_steps_pair_risky_count
future_K_steps_pair_severe_count
future_K_steps_min_pair_distance
```

### 10.4 主动策略是否过于激进

比较 B0/B2/B3：

```text
reset_count
proactive_reset_count
passive_reset_count
future pair risk
boundary distance
```

如果 B2/B3 显著增加 reset，但 pair risk 改善不明显，说明阈值或公式需要调整。

## 11. 分析注意事项

不要使用：

```text
execute_duration
真实运行时间
```

优先使用：

```text
decision_index
simulation time
累计行走距离
```

若要判断算法字段是否有预测价值，应优先使用：

```text
PassiveOnly + shadow logging
```

因为 B2/B3 的系统行为已经被 `W_H/G_peak` 干预，直接做相关性会产生偏差。

## 12. 最小处理流程

建议后续分析脚本按以下流程：

```text
1. 遍历 Proactive Reset Logs/trialId_*。
2. 读取 run_metadata.csv，确认配置。
3. 读取 decision_points.csv 作为主表。
4. 读取 user_samples.csv，按 time 聚合用户状态。
5. 读取 pair_samples.csv，按 time 聚合 pair risk。
6. 读取 reset_events.csv，映射到 decision_index。
7. 构造 future K steps 标签。
8. 做相关性、分位数对比、策略间 paired comparison。
```

