# Ryu-Kim Stage 4

Stage 4 starts from frozen Stage 1-3 artifacts. It must not modify Stage 1-3
predictions, split files, test samples, original metrics, or raw data.

## Completed Locally

- `fms_label_diagnostics/`: FMS update events, update direction/magnitude,
  stair duration, high-FMS events, and future 5s/10s FMS deltas as
  supervision-only targets.
- `final_report.md`: consolidated Stage 4 interpretation from downloaded server
  outputs.

## Server Diagnostics

Downloaded server outputs are currently under `stage4/` inside this directory
because the remote folder was copied with its parent path:

- `stage4/history_diagnostics/`
- `stage4/dose_diagnostics/`
- `stage4/static_diagnostics/`
- `stage4/multitask_diagnostics/`

The final report aggregates those files.

## Re-run Commands

Run smoke checks first:

```bash
conda activate ryu-kim
export PYTHONPATH=$PWD/python/src:$PWD

python scripts/train_ryu_kim_stage4_diagnostics.py --repo-root "$PWD" --experiment history --smoke-fold-only
python scripts/train_ryu_kim_stage4_diagnostics.py --repo-root "$PWD" --experiment dose --smoke-fold-only
python scripts/train_ryu_kim_stage4_diagnostics.py --repo-root "$PWD" --experiment static --smoke-fold-only
python scripts/train_ryu_kim_stage4_diagnostics.py --repo-root "$PWD" --experiment multitask --smoke-fold-only
```

Then run full diagnostics:

```bash
python scripts/train_ryu_kim_stage4_diagnostics.py --repo-root "$PWD" --experiment history 2>&1 | tee shared/data/exports/stage4/history_diagnostics/train_history.log
python scripts/train_ryu_kim_stage4_diagnostics.py --repo-root "$PWD" --experiment dose 2>&1 | tee shared/data/exports/stage4/dose_diagnostics/train_dose.log
python scripts/train_ryu_kim_stage4_diagnostics.py --repo-root "$PWD" --experiment static 2>&1 | tee shared/data/exports/stage4/static_diagnostics/train_static.log
python scripts/train_ryu_kim_stage4_diagnostics.py --repo-root "$PWD" --experiment multitask 2>&1 | tee shared/data/exports/stage4/multitask_diagnostics/train_multitask.log
```

## Required Interpretive Boundaries

- Future FMS deltas and update events are labels/targets only, never inputs.
- Static features must be called session-recorded static susceptibility features;
  they do not prove confirmed participant identity.
- All standardization, weights, event weights, and class weights are fitted from
  the current training fold only.
- Models must be compared to Stage 2 LSTM and Ridge on the same frozen split,
  with common-anchor paired comparisons for history length.
