# Task Analysis: Stage-1 Cybersickness Estimation

This document records implementation-facing decisions that complement
`PROJECT_CONTEXT.md` and `python/configs/stage1/TRAINING_SPEC.yaml`.

## FMS Semantics

FMS is not "training-only." It is the supervised reference value for
training, validation, and test evaluation. It must not enter the model's
runtime input.

The deployable model receives only participant static information and
historical motion data, then outputs an estimate on the FMS scale.

Preferred names:

- FMS-supervised real-time cybersickness severity estimator
- cybersickness severity estimate on the FMS scale

Avoid calling the output an "objective dizziness value." FMS is still a
subjective rating, even though the Ryu-Kim dataset provides dense,
time-resolved supervision.

## Research Stages

Project mainline:

```text
real-time cybersickness quantification base model
    -> RDW scene transfer and personalization
    -> adaptive RDW adjustment from quantified state
```

Current implementation scope is restricted to Stage 1. Do not implement
transfer learning, Unity integration, or RDW control while building the
first-stage pipeline. Split Stage 1 into independent tasks: data
inspection, causal window construction, baseline training, temporal
model training, offline evaluation, and streaming inference validation.

Stage 1: Internal validation on public data.

- Answer whether static information plus historical motion can estimate
  current FMS for unseen participants inside the Ryu-Kim data
  distribution.
- Use participant-level validation, model comparison, window-length
  comparison, feature ablation, inference-speed testing, and output
  stability testing.
- This stage only supports claims about the public dataset distribution.
  Cross-scene generalization is not proven.

Stage 2: Prospective external validation in Unity.

- Freeze the trained model and preprocessing parameters before data
  collection.
- Run the estimator in a Unity scene using static information and motion
  history as input.
- Participants still report FMS, but FMS is used only as post-hoc
  ground truth and must never be passed to the model.
- The first external validation should not let the model control RDW
  gains, so that estimation accuracy and intervention effects remain
  separable.

Stage 3: RDW data fine-tuning and validation.

- Collect data that includes RDW gains, resets, and spatial state.
- Fine-tune on some participants and test on fully held-out
  participants.
- Compare zero-shot and fine-tuned models before deciding whether model
  output should enter RDW control.

## Real-Time Model Requirements

All candidate models must be compatible with online estimation:

- unidirectional and causal;
- fixed historical window input;
- one current-FMS output per window;
- no bidirectional LSTM;
- no future padding;
- causal attention or strict historical-window Transformer inputs;
- no full-trajectory input at inference time.

Core comparison group:

- training-set mean predictor;
- static-feature Ridge;
- window-statistics Ridge;
- lightweight 1D CNN;
- unidirectional LSTM or GRU;
- causal TCN as a primary deployment candidate;
- compact causal Transformer.

Optional later models:

- CNN-GRU or CNN-LSTM;
- ordinal regression;
- uncertainty-aware regression.

Large language models and very large time-series models are not a
first-round priority for 2 Hz, single-value, real-time estimation.

## Window Lengths

The 20 second window is a default, not a fixed assumption. Compare:

```text
5s
10s
20s
40s
```

Report accuracy, high-FMS error, output stability, model latency, and
initial warmup time for each duration. Longer windows may capture
accumulation but increase startup delay and may reduce responsiveness.

## Streaming Consistency

Offline sliding-window prediction must match streaming rolling-buffer
prediction at the same timestamp, up to numerical tolerance.

Required comparison:

```text
offline_window_prediction
streaming_buffer_prediction
```

All preprocessing used in streaming must be causal. Do not use:

- centered moving averages;
- bidirectional Savitzky-Golay filters;
- interpolation that uses future samples;
- whole-sequence statistics for normalization.

End-to-end real-time latency should include feature computation,
resampling, standardization, model inference, and postprocessing.

## Output Tasks

Continuous regression remains the primary task:

```text
static information + historical motion -> current FMS-scale estimate
```

Ordinal regression may be added as an experimental comparison because
FMS is an ordered subjective scale. It does not replace continuous
regression.

Uncertainty output is optional and should be reserved for explicit
experiments, such as quantile regression, heteroscedastic regression,
ensembles, or conformal prediction.

Optional structured output:

```python
SeverityEstimate(
    mean,
    lower_bound=None,
    upper_bound=None
)
```

## FMS Label Characteristics

Ryu-Kim stores FMS approximately every 0.5 seconds, but participants may
only adjust FMS when needed. Long runs of identical FMS values can be
held labels rather than new subjective judgments.

The pipeline should derive `fms_update_event` and report:

- all windows;
- windows near FMS update events;
- windows in long unchanged-FMS intervals.

Event-aware sampling is an ablation only:

```text
ordinary participant-balanced sampling
moderately increased weight near FMS change points
```

It must not be enabled by default because over-weighting update regions
may make deployed predictions too volatile.

Do not collapse the task into assigning one end-of-experiment or
whole-segment label to a long window. The project should preserve
Ryu-Kim's time-resolved FMS supervision for real-time severity
estimation.

## Evaluation Beyond Aggregate MAE

Do not rely only on pooled-window MAE. Overlapping and flat windows can
hide failure on individual participants.

Add real-time quantification metrics:

- Concordance Correlation Coefficient;
- Bland-Altman agreement plot;
- systematic bias by FMS range;
- high-FMS underestimation analysis;
- participant-level timeline correlation;
- DTW or timeline-shape comparison;
- response delay after FMS changes;
- rising/falling direction correctness;
- adjacent prediction change;
- prediction total variation;
- abnormal jumps per minute;
- high-risk recall;
- per-participant MAE;
- fraction of participants beating baseline;
- worst 10% participant performance;
- subgroup errors by MSSQ, gender, and age group.

## External Validation Records

Unity validation should record enough data to reconstruct each
prediction:

```text
model input features
raw model output
smoothed model output
ground-truth FMS
FMS update time
model inference time
frame rate and dropped frames
whether the input window was complete
experimental condition
participant ID
timestamp
```

Recommended external validation levels:

1. non-RDW or original-scene validation;
2. fixed-RDW-condition validation where gains are preset and not model
   controlled;
3. post-fine-tuning validation on new participants.

This separates model error, scene transfer error, RDW motion-distribution
shift, and fine-tuning recovery.

## Future Extensions

Possible later directions:

- teacher-student training where richer physiological or gaze signals
  are available during training but deployment still uses motion and
  static features only;
- pre-experiment gait calibration in future RDW studies.

These are not version-1 requirements and should not be forced into the
Ryu-Kim model.

## Claim Boundaries

After public-data experiments only:

> We propose and evaluate a causal, many-to-one, real-time
> cybersickness severity estimation pipeline from participant static
> information and virtual motion data.

After Unity external validation:

> The model can estimate cybersickness severity on the FMS scale in new
> VR environments and participants.

After RDW fine-tuning and validation:

> The model output can be considered as a state input for adaptive RDW.

Adaptive RDW should initially use rule-based, small, constrained
adjustments. Do not assume that lowering gains when predicted sickness
increases is effective; RDW experiments must validate the effect of gain
adjustments on both cybersickness and walking experience before any
learned or stronger control policy is claimed.

The most important additions are prospective external validation,
streaming consistency, window-length experiments, real-time
quantification metrics, and FMS label-characteristic analysis.
