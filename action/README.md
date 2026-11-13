# GitHub Action

**Not implemented yet.** Milestone M5.

Planned interface:

```yaml
- uses: shellghostt/schemasentry@v1
  with:
    database-url: ${{ secrets.DATABASE_URL }}
    baseline: snapshots/main.json
    fail-on: high
```

Exit codes: `0` ok, `1` warning threshold crossed, `2` blocking risk found, `3` tool error.
