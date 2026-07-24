# Monorepo Layout

The repository is organized as one monorepo with independent Unity and Python workspaces connected through shared schemas.

```text
OpenRDW/
  unity/
    README.md
    OpenRDW/                 # target location for the Unity project
  python/
    README.md
    configs/stage1/
      TRAINING_SPEC.yaml     # stage-1 training and evaluation specification
    src/openrdw_ai/          # Python package code
    scripts/                 # training, export, analysis commands
    tests/                   # Python tests
  shared/
    schemas/
      episode.schema.json
      model-manifest.schema.json
    data/
      raw/
      processed/
      exports/
    models/
      checkpoints/
      onnx/
      manifests/
  docs/
    research/
      PROJECT_CONTEXT.md     # research background and stage boundaries
      TASK_ANALYSIS.md       # implementation-facing analysis and guardrails
  OpenRDW/                   # current Unity project location before migration
```

Ownership rules:

- Unity code should stay inside the Unity workspace.
- Python code should stay inside the Python workspace.
- Data and model artifacts shared by both sides should stay inside `shared`.
- Unity and Python should exchange files through schemas in `shared/schemas`.

Migration note:

The current Unity project still lives at `OpenRDW/`. Move it to `unity/OpenRDW/` in a separate migration commit after confirming Unity project references and ignored generated directories.
