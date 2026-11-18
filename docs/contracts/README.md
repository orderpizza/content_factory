# Executable Contracts

The complete current database DDL is
[application-schema.sql](application-schema.sql), owned by
[SQLite records](../specs/data-model.md#schema-and-record-inventory). Schema version 20 and its exact
checksum are validated at runtime. Setup creates a fresh database and never
converts an incompatible schema. The explicit additive
[migration-18-19.sql](migration-18-19.sql) is retained within the fresh contract;
`database.migrate_delivery` still stops at v19 and validates the pinned historical v18 contract before
applying it with backup/transaction checks. See the
[operator procedure](../operations.md#offline-database-migration-for-delivery-revisions).

[configuration-manifest-v4.schema.json](configuration-manifest-v4.schema.json)
describes Detection configuration; `src/detection/configuration.py` enforces
its runtime semantics.

Gemini response schemas live alongside their producers in
`src/workflow/gemini_intake.py`, `gemini_determination.py`,
`editorial_planning.py`, `gemini_generation.py` and `gemini_adaptation.py`. Their local semantic validators
are authoritative; SQL JSON validity alone is insufficient.

[migration-19-20.sql](migration-19-20.sql) is the exact final suffix of the fresh
contract. `database.migrate_measurement` reconstructs and validates the pinned v19
contract before a separate backed-up upgrade. Both historical migrations retain
their original version boundaries. See the
[measurement procedure](../operations.md#offline-database-migration-for-measurement).

The fresh SQL file owns the full schema; migration suffixes are checked against
it before migration. `MANIFEST.in` includes all SQL resources in
source distributions; the `setup.py` / `build_support.py` hook copies identical
bytes into `content_factory_resources` in wheels. Editable checkouts resolve the
canonical file directly. Packaging tests build from an sdist and initialize a
fresh database from the installed wheel outside the checkout.
