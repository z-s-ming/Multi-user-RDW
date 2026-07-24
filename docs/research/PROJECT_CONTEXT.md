# Project Context: Cybersickness Prediction for Future Adaptive RDW

Companion documents:

- `TASK_ANALYSIS.md`: implementation-facing task analysis and stage
  boundaries.
- `../../python/configs/stage1/TRAINING_SPEC.yaml`: stage-1 training,
  evaluation, and reporting specification.

## 1. Research background

This project studies the integration of real-time cybersickness
prediction with redirected walking (RDW).

The long-term goal is to build a system that:

1. estimates or predicts a user's cybersickness severity in real time;
2. uses this estimate as an input to an RDW adaptation strategy;
3. eventually adjusts RDW parameters such as translation gain,
   rotation gain, curvature gain, or reset strategy.

The project will be implemented in multiple stages.

The current stage only concerns the cybersickness prediction model.
It does not yet train an RDW control policy.

---

## 2. Source dataset

The first-stage model uses the public dataset provided by Ryu and Kim:

"Predicting Cybersickness Trend and Extent based on FMS Labeled Dataset"

The dataset contains temporally dense cybersickness labels sampled
approximately every 0.5 seconds.

Dynamic time-series features include:

- acceleration_x;
- acceleration_y;
- acceleration_z;
- angular_velocity_x;
- angular_velocity_y;
- angular_velocity_z.

The raw timestamp should be used first for sorting, window construction,
and sampling-interval checks. It should not be included as a model
feature by default because absolute time can act as a proxy for progress
through a fixed experimental trajectory.

```yaml
include_timestamp_as_feature: false
```

Timestamp may be included only in an explicit ablation experiment.

The regression target is:

- FMS, representing the reported cybersickness severity.

FMS is the supervised reference value for training, validation, and test
evaluation. It is not a runtime model input. The model output should be
understood as a cybersickness severity estimate on the FMS scale, not as
an objective dizziness value.

Static participant features include:

- age;
- gender;
- MSSQ.

The original study used complete fixed-length sequences and predicted
an FMS value for every timestep in the sequence.

This project intentionally does NOT reproduce that sequence-to-sequence
formulation.

---

## 3. 当前阶段目标

当前阶段不预先假定基于 Ryu-Kim 数据训练的模型足以直接
用于 RDW 控制。

当前阶段属于公开数据上的内部模型验证。它只能证明模型在
Ryu-Kim 数据分布内对训练时未见过的参与者是否可行，不能
证明跨设备、跨场景或 RDW 场景中的泛化能力。

当前 FMS 估计是第一阶段的主要任务。本阶段首先验证：
仅使用虚拟运动特征和参与者静态信息时，模型能否可信地
跨参与者估计当前晕动程度。

当前阶段依次研究以下任务：

1. 当前 FMS 状态估计：
   使用过去一段运动数据预测窗口终点时刻的 FMS。

2. 未来 FMS 预测：
   作为探索性任务保留，在同一数据管线上评估未来不同
   时间范围的 FMS 可预测性和可信度。初始考虑 2.5 秒、
   5 秒和 10 秒。

3. 晕动动态状态建模：
   趋势预测不应仅定义为“未来是否恶化”的二分类任务。
   由于晕动症具有累积性、时间滞后、个体差异和恢复过程，
   模型应尽可能描述其连续动态状态。

除当前 FMS 外，本阶段还应区分近期已发生的状态变化和
探索性的未来预测目标。未来 RDW 系统将根据
晕动程度、近期变化速度、累积状态和预测置信度，对增益进行
连续、分级的小幅调整，而不是仅根据一个二元恶化标签决定
是否干预。

概念上，预测器可以输出类似：

```text
当前晕动程度 FMS(t)
recent_fms_slope       # 根据过去和当前预测计算，实时可用
future_fms_delta       # 探索性未来预测目标，需要未来标签
未来 FMS(t + horizon)  # 探索性未来预测目标
累积晕动负荷           # 未来探索性派生状态，第一版不作为监督目标
预测不确定性
```

`recent_fms_slope` and `future_fms_delta` must not be conflated.
`recent_fms_slope` is computed only from past and current model outputs
and can be available online. `future_fms_delta`, such as
`FMS(t + 5s) - FMS(t)`, is an exploratory future-prediction target and
requires future labels during offline training and evaluation.

累积晕动负荷属于未来探索性派生状态，具体定义需要后续确定；
第一版不得自行假设标签或直接作为模型监督目标。未来可能的
定义包括预测 FMS 的时间积分、指数加权累积，或超过某个基线
后的累积值，但这些属于研究设计，不能由实现自行决定。

RDW 控制器未来接收的也不应是布尔标签，而应是类似：

```text
[FMS水平, 上升速度, 累积负荷, 距离风险阈值, 置信度]
```

如果仍需要离散趋势标签，应优先考虑：

```text
快速上升
缓慢上升
高位稳定
低位稳定
缓慢恢复
快速恢复
```

而不是“恶化／不恶化”。

模型是否进入后续 RDW 系统，取决于以下评估结果：

- 当前和未来 FMS 数值预测误差；
- 不同预测范围下的性能下降；
- 对高晕动状态的识别能力；
- 对近期变化速度和未来变化量的估计能力；
- 能够提供的有效提前时间；
- 跨参与者泛化能力；
- 实时推理稳定性。

未来预测对 RDW 的价值在于提前调整，但它不是第一阶段
必须成功的前提。只有当未来预测相较于持续性基线具有稳定
优势，并能提供足够提前量时，才考虑将其作为 RDW 调整模块
的输入。

如果未来 FMS 数值预测具有足够的准确性和稳定性，则将其
作为 RDW 调整模块的一项输入。如果未来预测不足，则使用
当前状态和近期变化速率构成控制输入。累积状态只有在后续
研究给出明确操作性定义后，才可进入控制输入。

如果当前状态估计、未来预测和动态状态估计均不能满足要求，
则不能直接将当前模型用于 RDW 控制，需要等待收集 RDW 场景
数据后重新训练或微调。

---

## 4. Important label rule

For the default current-state task, each time-series window must be
labeled using the FMS value at the window's terminal timestep.

For example, with:

- sampling frequency = 2 Hz;
- window duration = 20 seconds;

one model input contains:

```text
40 timesteps x number_of_dynamic_features
```

and the default target is:

```text
FMS at timestep 40
```

For exploratory future prediction, the target may instead be the FMS at
the configured horizon after the terminal timestep:

```text
FMS(t + prediction_horizon_seconds)
```

The model must never use samples after the input terminal time t as
input features. Future samples may only be used to construct exploratory
future targets during offline training and evaluation.

For future-delta experiments, name the target explicitly as:

```text
future_fms_delta = FMS(t + horizon) - FMS(t)
```

This target is not available online and must never be used as a real-time
input feature.

The window duration, stride, and prediction horizon must be
configuration parameters rather than hard-coded constants.

Suggested initial defaults:

- sample_interval_seconds: 0.5
- sampling_rate_hz: 2
- window_duration_seconds: 20
- window_length: 40
- stride_seconds: 0.5
- prediction_horizon_seconds: 0

The version-1 default remains:

```yaml
prediction_horizon_seconds: 0
```

Exploratory future-prediction experiments may set:

```yaml
prediction_horizon_seconds: 2.5
prediction_horizon_seconds: 5
prediction_horizon_seconds: 10
```

---

## 5. FMS must not be used as an input in version 1

FMS is the prediction target.

Historical FMS values must not be included in the model input in the
initial version.

This restriction is important because the intended deployment scenario
should estimate sickness from motion and participant information
without requiring the user to continuously provide previous FMS values.

The data pipeline may retain the raw FMS column for target generation,
but it must not include FMS in the input feature tensor.

Provide a configuration field such as:

```text
include_fms_history: false
```

The default and version-1 value must be false.

---

## 6. Data splitting and leakage prevention

Data must be split by participant, not by individual rows or windows.

All sessions and all windows from one participant must belong to only
one of:

- training set;
- validation set;
- test set.

Do not randomly split overlapping windows.

A forbidden split would be:

- one window from participant P001 in training;
- another window from participant P001 in testing.

Use participant_id as the primary grouping key.

If the dataset contains multiple sessions or experiment conditions,
preserve:

- participant_id;
- session_id;
- condition_id;
- timestep or timestamp.

Possible splitting implementations include:

- GroupShuffleSplit;
- GroupKFold;
- Leave-One-Subject-Out evaluation.

The first implementation should provide a fixed participant-level
train/validation/test split and optionally GroupKFold evaluation.

The random seed and participant IDs assigned to each split must be
saved for reproducibility.

---

## 7. Preprocessing rules

The preprocessing pipeline must:

1. inspect dataset files and infer or map their column names;
2. sort each session by timestamp;
3. detect missing, duplicated, or invalid rows;
4. ensure that windows never cross participant or session boundaries;
5. standardize continuous input features;
6. encode categorical static features such as gender;
7. create sliding windows;
8. assign terminal-frame FMS labels;
9. derive and save FMS update-event indicators where possible;
10. save preprocessing metadata.

Although the Ryu-Kim dataset stores FMS values approximately every 0.5
seconds, users may adjust FMS only when needed, so many consecutive
samples can simply hold the previous reported value. The pipeline should
record or derive an `fms_update_event` flag where possible, for example
when the FMS value changes from the previous sample within a session.
Evaluation should separately analyze windows near FMS update events so
that good aggregate metrics are not driven only by long flat intervals.

Scalers and encoders must be fitted using the training set only.

The validation and test sets must use the scaler fitted on the training
set.

Save at least:

- dynamic feature order;
- static feature order;
- feature means and standard deviations;
- categorical encoding rules;
- sampling interval;
- window length;
- target definition;
- dataset split;
- model configuration.

Do not silently drop large amounts of data. Produce a preprocessing
report containing:

- number of participants;
- number of sessions;
- number of raw rows;
- number of valid rows;
- number of generated windows;
- number of discarded sessions or windows;
- reasons for discarding data;
- FMS distribution;
- number and distribution of FMS update events;
- performance slices near FMS update events where available;
- windows per participant.

---

## 8. Model formulation

The model must use a modular structure that can later be extended with
RDW-specific features.

Recommended conceptual architecture:

```text
common dynamic features
         |
         v
shared temporal encoder
         |
         +------------------+
                            |
static participant encoder  |
         |                  |
         +------ fusion ----+
                   |
             FMS regression head
                   |
               predicted FMS
```

The shared temporal encoder may initially be implemented using one
sequence architecture such as:

- LSTM;
- TCN;
- Transformer encoder.

For the first implementation, prioritize correctness, reproducibility,
and extensibility over architectural complexity.

The output shape must be:

```text
[batch_size, 1]
```

It must not be:

```text
[batch_size, sequence_length]
```

The model class should expose the temporal encoder separately from the
regression head so that the encoder weights can later be reused.

Suggested structure:

```text
TemporalEncoder
StaticFeatureEncoder
FeatureFusion
FMSRegressionHead
CybersicknessModel
```

Avoid defining the entire model as one indivisible sequential block.

---

## 9. Future RDW extension

A future dataset will be collected from a Unity-based redirected
walking experiment.

The future dataset will retain the shared motion features where
possible and add RDW-specific dynamic features, potentially including:

- translation_gain;
- rotation_gain;
- curvature_gain;
- reset_flag;
- reset_type;
- distance_to_boundary;
- RDW steering state;
- physical walking velocity;
- virtual walking velocity;
- physical and virtual pose information.

The future model should conceptually support:

```text
shared motion features -> pretrained temporal encoder -> h_common

RDW features -> RDW-specific encoder -> h_rdw

static participant features -> static encoder -> h_static

concatenate(h_common, h_rdw, h_static)
                |
         task-specific head
```

The version-1 implementation does not need to process RDW features,
but the code architecture must not prevent adding an RDW branch later.

Do not modify the meaning or ordering of the common feature interface
when adding RDW features.

The shared temporal encoder learned from the Ryu-Kim dataset should be
saveable and loadable independently.

---

## 10. Future fine-tuning strategy

When the RDW dataset becomes available, the intended training process
is:

Stage A:
- load the pretrained shared temporal encoder;
- freeze the shared temporal encoder;
- train the new RDW feature encoder and prediction head.

Stage B:
- unfreeze the later layers of the shared encoder;
- fine-tune using a lower learning rate.

Stage C:
- optionally unfreeze the complete model;
- perform end-to-end fine-tuning with a still lower learning rate.

The current checkpoint format must support this process.

Save at least:

- full model checkpoint;
- temporal encoder checkpoint;
- optimizer-independent model weights;
- model configuration;
- preprocessing configuration.

---

## 11. Relationship between prediction and mitigation

The current dataset contains sickness labels but does not contain
experimental evidence about which RDW action is effective.

Therefore, the first-stage model can learn:

```text
motion + participant information -> cybersickness dynamic state
```

It cannot learn:

```text
current state -> optimal RDW gain adjustment
```

Do not train an RDW action-selection model using the Ryu-Kim dataset.

Prediction and mitigation must be separate modules.

The Ryu-Kim dataset can train a model of cybersickness dynamics, but it
cannot train how much RDW gain should be adjusted. After RDW scenario
data is collected with gain values and gain changes, a later model may
learn a conditional future-state predictor:

```text
current cybersickness state + current gain + candidate gain change
                    |
                    v
             future FMS change
```

Action-conditioned future-state prediction is one candidate approach.
Learning intervention effects requires sufficiently varied and
preferably randomized or counterbalanced gain conditions; otherwise the
model estimates observational associations rather than causal effects.
A trend class or dynamic-state estimate from the Ryu-Kim dataset must
not be mechanically mapped to a fixed gain change and treated as a
learned control policy.

Suggested software interfaces:

```text
CybersicknessPredictor
    input: historical feature window
    output: current FMS estimate

MitigationPolicy
    input: predicted FMS, dynamic-state estimates, confidence, and system state
    output: mitigation command
```

In version 1, MitigationPolicy may be:

- an unimplemented interface;
- a simple rule-based placeholder;
- an offline simulation component.

Any threshold mapping from predicted FMS to an intervention must be
clearly marked as heuristic, not learned from the Ryu-Kim dataset.

---

## 12. Initial experimental baselines

The evaluation should include simple baselines in addition to the main
sequence model.

At minimum:

1. training-set mean FMS predictor;
2. static-feature-only regression baseline;
3. oracle persistence baseline for future prediction;
4. deployable predicted-current persistence baseline;
5. motion-window sequence model.

The oracle persistence baseline is especially important for future FMS
prediction:

```text
FMS(t + horizon) ~= FMS(t)
```

This baseline uses the true current `FMS(t)`. It is an oracle baseline
for offline evaluation only because the version-1 deployment setting does
not have true current FMS as an input. It tests whether future prediction
contains information beyond simply holding the current state.

Also include a deployable persistence baseline:

```text
FMS(t + horizon) ~= predicted_current_FMS(t)
```

This baseline uses the current-state estimator's output and carries it
forward to the future horizon.

Because FMS has cumulative dynamics and may change slowly over short
intervals, future-prediction models must show stable improvement over
both persistence baselines before their forecasts are considered useful
for RDW.

Optionally include:

- linear regression on aggregated window statistics;
- small MLP on window statistics;
- LSTM or Transformer comparison.

The goal is to verify that the sequence model learns useful temporal
information rather than only reproducing the population mean or static
participant susceptibility.

---

## 13. Evaluation metrics

For FMS regression, report:

- MAE;
- RMSE;
- R-squared;
- Pearson correlation, if appropriate.

For exploratory future FMS prediction, report the same metrics for each
prediction horizon and compare them against both persistence baselines:

```text
Oracle:     FMS(t + horizon) ~= FMS(t)
Deployable: FMS(t + horizon) ~= predicted_current_FMS(t)
```

Future prediction should only be considered meaningful if it provides a
stable advantage over these baselines and enough effective lead time for
RDW adaptation. The oracle baseline is not deployable; it is only a
diagnostic for whether the future task contains information beyond
current-state persistence.

For dynamic-state estimates, also report where possible:

- short-term and medium-term delta-FMS error;
- `recent_fms_slope` stability, computed from past and current predictions;
- `future_fms_delta` error for exploratory future-prediction experiments;
- ability to identify high-FMS states;
- stability of predictions over consecutive windows;
- uncertainty calibration if uncertainty estimates are implemented.

Also report metrics by participant where possible, not only metrics
over all windows.

Generate:

- true versus predicted scatter plot;
- residual distribution;
- example FMS curves for held-out participants;
- ground-truth and prediction timelines;
- error distribution by FMS range;
- horizon-wise performance comparison;
- oracle and deployable persistence-baseline comparison;
- performance near FMS update events;
- participant-level summary table.

Because overlapping windows are highly correlated, do not claim that
the number of windows equals the number of independent observations.

---

## 14. Real-time inference requirement

The final model will eventually run from a rolling buffer in Unity.

The version-1 deployable inference interface may remain minimal:

```python
predict_current_fms(
    dynamic_window,
    static_features
) -> float
```

Exploratory future-prediction or dynamic-state experiments should use a
separate structured result and must not force version 1 to implement all
fields:

```python
PredictionResult(
    current_fms,
    future_fms=None,
    recent_slope=None,
    future_delta=None,
    uncertainty=None
)
```

The version-1 inference function must:

- validate feature names and order;
- apply saved preprocessing parameters;
- require exactly the configured window length;
- return one FMS prediction;
- avoid accessing future data;
- support batch size 1.

`recent_slope` may be computed online from a history of current-FMS
predictions. `future_fms`, `future_delta`, and uncertainty estimates are
optional exploratory outputs and must be enabled explicitly.

The first stage does not require Unity integration, but the exported
model and preprocessing metadata must be suitable for later deployment.

Potential future export formats include ONNX.

---

## 15. Repository responsibilities

The Python module is responsible for:

- inspecting and validating the Ryu-Kim dataset;
- preprocessing;
- participant-level splitting;
- window construction;
- training;
- evaluation;
- checkpoint export;
- inference testing.

Unity is not part of the current implementation task.

Do not create or modify Unity scripts during this stage unless
explicitly requested.

---

## 16. Non-goals for version 1

Version 1 does not:

- reproduce the paper's complete sequence-to-sequence output;
- predict an entire 420-point FMS sequence;
- use future frames when estimating the current FMS;
- use historical FMS as an input;
- learn an RDW control policy;
- determine the optimal gain;
- perform closed-loop user experiments;
- claim that reducing gain necessarily reduces cybersickness;
- require physiological sensors;
- require Unity integration.

---

## 17. Definition of done

The first-stage implementation is complete when it can:

1. load the Ryu-Kim dataset;
2. produce a dataset inspection report;
3. create causal sliding windows;
4. split data by participant without leakage;
5. train at least one many-to-one current-FMS regression model;
6. evaluate it against basic baselines;
7. save model and preprocessing metadata;
8. reload the saved model;
9. predict one scalar FMS value from one historical window;
10. save the temporal encoder separately for future RDW fine-tuning;
11. document how RDW features will later be attached without changing
    the shared motion encoder.

Exploratory future-horizon prediction and dynamic-state outputs should
reuse the same leakage-safe windowing and evaluation pipeline, but they
are not required to outperform baselines before the first current-FMS
estimation pipeline is considered implemented.
