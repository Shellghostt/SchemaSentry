# SS005: integer NOT NULL fast default

Reviewed edge case. A fitting built-in integer literal supplies a nonnull missing value. The existing nonempty heap need not be scanned or rewritten on PG 13/15/16; SS003 retains its independent compatibility policy. Live checks pin the heap file and atthasmissing.
