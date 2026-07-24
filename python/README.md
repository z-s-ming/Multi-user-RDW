# Python Workspace

Python-side training, analysis, evaluation, and model export code lives here.

Suggested package layout:

- `src/openrdw_ai/` for reusable Python modules
- `scripts/` for command-line workflows
- `tests/` for Python tests
- `notebooks/` for exploratory work, if needed

Python code should read and write shared inputs through `../shared/schemas` contracts, not by depending on Unity project internals.

