# SS005: add-notnull-null-default

Reviewed additional edge case. A nonvolatile NULL default cannot prove the added column is nonnull. PostgreSQL rejects existing rows.
