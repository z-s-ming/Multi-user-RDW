# Ryu-Kim Dynamic Baseline Server Runbook

This document records the repeatable server steps for running the controlled
Ryu-Kim dynamic baseline. It does not cover Unity, cross-dataset transfer, or
real-time deployment.

## Scope

The run produces a `raw_pa_id-group-disjoint dynamic baseline` on the current
public Ryu-Kim data snapshot.

Required declarations for any report using these outputs:

- The current public repository snapshot contains 428 sessions.
- True participant identity is still unconfirmed.
- The split is a `raw_pa_id-group-disjoint split`, not a confirmed
  participant-disjoint split.
- Static personalization is not included.
- Results do not represent cross-dataset transfer or Unity real-time deployment
  performance.

## Upload Layout

Upload these directories while preserving their relative paths:

```text
configs/
scripts/
tests/
python/
shared/
```

The server project root should then look like:

```text
openRDW/
  configs/
  scripts/
  tests/
  python/
  shared/
```

## Conda Environment

From the project root:

```bash
cd ~/openRDW
conda create -n ryu-kim python=3.10 -y
conda activate ryu-kim
```

Optional packages for later accelerated implementations:

```bash
pip install -U pip
pip install numpy pandas scikit-learn pyyaml
```

The current baseline implementation and tests do not require PyTorch. If a
future LSTM/TCN implementation is enabled, install a PyTorch build matching the
server CUDA version.

## Shell Environment

Run this in every new shell before tests or training:

```bash
cd ~/openRDW
conda activate ryu-kim

export PYTHONPATH=$PWD/python/src
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export CUDA_VISIBLE_DEVICES=0
```

`CUDA_VISIBLE_DEVICES=0` is harmless for the current CPU/standard-library
baseline and keeps later GPU runs pinned to one GPU.

## Data Check

Confirm the raw CSV files are present:

```bash
ls shared/data/raw/pretraining/2025_Cybersickness_dataset/Dataset | head
```

Expected filenames look like:

```text
PA100_Reverse_Optical_Flow.csv
PA10_Base_11_31_04_AM.csv
...
```

## Tests

Run both test suites before training:

```bash
python -m unittest discover -s python/tests
python -m unittest discover -s tests
```

Expected result:

```text
OK
```

If `ModuleNotFoundError: No module named 'openrdw_ai'` appears, `PYTHONPATH` was
not set correctly. Re-run:

```bash
export PYTHONPATH=$PWD/python/src
```

## Full Training With Screen

Use `screen` so the run survives SSH disconnects.

Start a named session:

```bash
screen -S ryu_kim_train
```

Inside the screen session, from the project root:

```bash
cd ~/openRDW
conda activate ryu-kim

export PYTHONPATH=$PWD/python/src
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export CUDA_VISIBLE_DEVICES=0

mkdir -p reports/ryu_kim_dynamic_baseline

python scripts/train_ryu_kim_dynamic_baseline.py \
  --repo-root "$PWD" \
  --durations 10,30,60 \
  --folds 5 \
  2>&1 | tee reports/ryu_kim_dynamic_baseline/train_full.log
```

The script prints progress messages such as:

```text
[setup] loaded 428 sessions
[10s] generating causal windows
[10s][fold 1/5][ridge_window_stats] training
[10s][fold 1/5][ridge_window_stats] done: MAE=..., RMSE=...
```

Because output is line-buffered and `PYTHONUNBUFFERED=1` is set, these messages
should appear in both the terminal and `train_full.log` while the job is
running.

Detach without stopping the run:

```text
Ctrl+A
D
```

Reconnect later:

```bash
screen -r ryu_kim_train
```

List sessions if needed:

```bash
screen -ls
```

## Quick Single-Window Run

For a shorter smoke-style training run:

```bash
python scripts/train_ryu_kim_dynamic_baseline.py \
  --repo-root "$PWD" \
  --durations 10 \
  --folds 5 \
  2>&1 | tee reports/ryu_kim_dynamic_baseline/train_10s.log
```

## Output Files

Outputs are written to:

```text
reports/ryu_kim_dynamic_baseline/
```

Important files:

```text
README.md
summary.json
metrics_by_fold.csv
window_counts.csv
predictions_10s.csv
predictions_30s.csv
predictions_60s.csv
prediction_curves_*_causal_tcn_linear.csv
train_full.log
```

Check summary:

```bash
cat reports/ryu_kim_dynamic_baseline/README.md
```

Monitor a running log from another shell:

```bash
tail -f reports/ryu_kim_dynamic_baseline/train_full.log
```

## What This Run Produces

The run compares:

- training-fold FMS mean baseline;
- Ridge regression on dynamic window statistics;
- `causal_tcn_linear`, a lightweight causal TCN-style lag feature baseline with
  a Ridge head.

Window lengths:

- 10 seconds;
- 30 seconds;
- 60 seconds.

Inputs:

- `acceleration_x`;
- `acceleration_y`;
- `acceleration_z`;
- `angular_velocity_x`;
- `angular_velocity_y`;
- `angular_velocity_z`.

Forbidden model inputs:

- FMS history;
- age;
- gender;
- MSSQ;
- participant ID;
- session ID;
- condition;
- filename;
- future frames.

## Common Issues

### `openrdw_ai` Import Error

Cause: missing `PYTHONPATH`.

Fix:

```bash
export PYTHONPATH=$PWD/python/src
```

### Conda And Venv Both Active

If the prompt shows both `(.venv)` and `(base)` or `(ryu-kim)`, deactivate and
use one environment only:

```bash
deactivate 2>/dev/null || true
conda deactivate
conda activate ryu-kim
```

### Training Seems Slow

The current implementation is dependency-light and mostly CPU/standard-library
based, so a 3090 may not be fully used. This is expected for this baseline.
For faster future full runs, replace the Ridge and sequence models with
NumPy/scikit-learn/PyTorch implementations after the controlled baseline is
validated.

### SSH Disconnect Risk

Use `screen`. Detaching with `Ctrl+A`, then `D`, keeps the run alive.

### Need To Stop A Run

Reconnect:

```bash
screen -r ryu_kim_train
```

Then press:

```text
Ctrl+C
```

Do not delete raw data. Partial files under `reports/ryu_kim_dynamic_baseline/`
can be removed before a clean rerun if the previous run was interrupted.
