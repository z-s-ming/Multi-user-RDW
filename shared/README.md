# Shared Workspace

Shared data, trained models, and schema contracts live here. Unity and Python should treat this folder as the integration boundary.

Directory roles:

- `schemas/`: versioned JSON schemas and data contracts used by both runtimes.
- `data/raw/`: source experiment data that should not be rewritten in place.
- `data/raw/pretraining/`: external pretraining datasets cloned or downloaded for local use.
- `data/processed/`: normalized datasets ready for training, evaluation, or Unity playback.
- `data/exports/`: generated exchange files emitted by either Unity or Python.
- `models/onnx/`: exported models consumable by Unity.
- `models/checkpoints/`: Python training checkpoints.
- `models/manifests/`: metadata that describes model inputs, outputs, metrics, and compatible schema versions.

Rule of thumb: Unity owns simulation/runtime behavior, Python owns training/analysis behavior, and `shared/schemas` owns the contract between them.
