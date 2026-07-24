# Ryu-Kim Identity Resolution

This second-round audit does not modify raw data and does not train models.

## Paper Counts Versus Local Files

- User-provided paper statistics: four participant batches of 48, 37, 31, and 40, with 427 experiments.
- Local dataset copy: 428 CSV files.
- Local raw PA prefixes: 86 unique `PAxx` prefixes.
- The local `PAxx` namespace is not globally unique participant identity evidence. It appears to encode file-batch/session naming, not a single global subject table.
- The extra local CSV count versus 427 is unresolved from the local readme and git history; it remains an audit issue rather than an assumed duplicate.

Inferred filename cohorts, used only as provenance buckets:
- cohort_pa001_099_mixed_conditions: 390 files
- cohort_pa100_199_reverse_optical_flow: 18 files
- cohort_pa200_299_noise: 20 files

## Identity Policy

- `raw_pa_id` is the parsed filename prefix only.
- `subject_uid_candidate` is `inferred_cohort_id:raw_pa_id` and remains unresolved.
- Age, gender, and MSSQ are consistency checks only; identical static values never confirm identity.
- Static conflicts block static personalization and are never resolved by automatic merging.

## Duplicate Checks

- No confirmed duplicate groups were found by the implemented exact hash checks.

Checks performed:
- SHA256-identical files.
- Content-identical sessions after ignoring filenames.
- Dynamic sequence identical after excluding static fields.
- First-420-row dynamic sequence exact equality.
- Time-series plus FMS exact equality.

High-similarity first-420 matching uses row-level dynamic equality ratio >= 0.99 within normalized-condition buckets; matching candidates are review-only, not confirmed duplicates.

## Missingness

- Rows in missingness table: 4708.
- Angular velocity Y/Z sessions with missing values: 162 column-session records.
- Angular velocity Y/Z missing patterns: `{'contiguous missing block': 134, 'sporadic missing': 28}`.
- Missingness classes: none, sporadic missing, contiguous missing block, entire-column missing, and condition/cohort-specific missing.
- No interpolation or imputation is performed in this task.

## Gate Status

- GATE_A_DYNAMIC_BASELINE: blocked; blockers: ['Trusted split unit is unresolved because PAxx is not a confirmed globally unique participant ID.']
- GATE_B_STATIC_PERSONALIZATION: blocked; blockers: ['Participant identity is unresolved; static personalization cannot treat candidates as confirmed people.']
- GATE_C_CROSS_DATASET_TRANSFER: blocked; blockers: ['Acceleration unit unresolved.', 'Angular velocity unit unresolved.', 'Coordinate frame unresolved.', 'Feature computation provenance unresolved.']
- GATE_D_REALTIME_DEPLOYMENT: blocked; blockers: ['Acceleration unit unresolved.', 'Angular velocity unit unresolved.', 'Coordinate frame unresolved.', 'Feature computation provenance unresolved.', 'Runtime missing-data behavior is not defined.']
