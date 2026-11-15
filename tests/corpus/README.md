# Golden migration corpus

This is the most important directory in the repository.

Each case is a directory:

```
corpus/0007_add_not_null_without_default/
  before.sql      schema before the migration
  migration.sql   the migration under test
  before.json     reviewed input snapshot for offline classification
  after.json      reviewed resulting/desired snapshot
  expected.json   rule ID, category, projected findings and parser status
  notes.md        why this classification is correct
```

A rule change that breaks any case here is wrong, not "stricter". Growing this corpus is the primary
way to improve accuracy.

M3 expectations contain base severity and confidence, not aggregate risk or public CLI exit codes.
Those contracts remain M4. Every SS001–SS007 rule has positive, negative and edge cases; extra cases
cover type/USING/version ambiguity, CHECK validation, FK index keys, renames and function resolution.
Expected findings are reviewed data and must never be regenerated from classifier output.

Live tests apply only these committed synthetic SQL files to task-owned disposable test databases.
Cases with legacy/contradictory metadata or unsupported versions are offline-only. Cases that contain
pre-existing NULLs pin PostgreSQL's expected rejection of SET NOT NULL; their after.json is the desired
schema, not a claim that the failed statement changed the database. Migration input in the product is
parsed as data and never executed. Existing M2 structural fixture pairs remain separate and unchanged.
