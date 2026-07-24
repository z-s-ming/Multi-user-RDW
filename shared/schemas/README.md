# Shared Schemas

Schemas define the files exchanged between Unity and Python.

Recommended convention:

- Additive changes keep the same major version.
- Breaking changes create a new schema file or increment the major schema id.
- Data files and model manifests should include `schema_version`.
- Unity and Python should validate at the boundary before consuming shared files.

