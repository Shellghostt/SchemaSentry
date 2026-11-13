# Golden migration corpus

This is the most important directory in the repository.

Each case is a directory:

```
corpus/0007_add_not_null_without_default/
  before.sql      schema before the migration
  migration.sql   the migration under test
  expected.json   {"changes": [...], "risk": "high", "exit_code": 2}
  notes.md        why this classification is correct
```

A rule change that breaks any case here is wrong, not "stricter". Growing this corpus is the primary
way to improve accuracy.
