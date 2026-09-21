# Executable Contracts

The complete current database DDL is
[application-schema.sql](application-schema.sql), owned by
[SQLite records](../specs/data/records.md). Schema version 7 and its exact
checksum are validated at runtime. Setup creates a fresh database and never
converts an incompatible schema.

[configuration-manifest-v4.schema.json](configuration-manifest-v4.schema.json)
describes Detection configuration; `src/detection/configuration.py` enforces
its runtime semantics.

Gemini response schemas live alongside their producers in
`src/workflow/gemini_intake.py`, `gemini_determination.py`,
`gemini_generation.py` and `gemini_adaptation.py`. Their local semantic validators
are authoritative; SQL JSON validity alone is insufficient.

[The system guide](../system.md#document-router) is the single narrative-owner router. Future functionality is
separate in the [implementation plan](../plans/target-implementation.md); no
unused draft payload is an active contract.
