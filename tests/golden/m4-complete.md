# SchemaSentry assessment

Report v1; policy v1; tool 0\.1\.0.

Analysis: **complete**; overall risk: **high**; threshold: **high**.

This is an observed-state assessment, with requested SQL evidence. It does not predict or apply a migration.

Before: snapshot v1, catalog evidence 1, postgres 16\.4, capture 2026\-11\-17T00\:00\:00Z; digest afdfc5546bef3a94903e8a8b6756eab81f56f26aca332045720d72a79fa0a225.

After: snapshot v1, catalog evidence 1, postgres 16\.4, capture 2026\-11\-17T00\:00\:00Z; digest 5d570ffc1ff397593d7f3fc239022e04270ca5741c3edbbb4f2264f3726135cd.

## SS008: constraint\_validation\_requested

Object: public / users / amount\_positive.

Base severity: **high**; final risk: **high**; confidence: **high**.

Effects: lock access_exclusive; scan required; rewrite not_required.

- Evidence (snapshot): Added check constraint &#x27;amount\_positive&#x27;; captured validation is known\.
- Evidence (migration) (line 1, column 1, chars 0:75): ALTER TABLE public\.users ADD CONSTRAINT amount\_positive CHECK \(amount &gt; 0\);

- Modifier row_estimate: not_applied, +0; value 0. Catalog rowEstimate is an estimate; mutually exclusive strict size tiers apply\.
- Modifier incoming_foreign_keys: not_applied, +0; value 0. Distinct incoming named FK constraints target this captured table, including outside\-schema sources when known\.
- Modifier service_reader_lock: unknown, +0; value unavailable. Reader ownership is unavailable under rename\-hints v1\.

Estimated seconds: unavailable.

Alternative: For eligible CHECK\/FK only, consider ADD CONSTRAINT \.\.\. NOT VALID, then VALIDATE CONSTRAINT separately\. Both stages still acquire locks and NOT VALID enforces new writes\. This is not an alternative for UNIQUE, PRIMARY KEY or NOT NULL\.

- Limitation: SQL is requested evidence, not proof that it executed\.
- Limitation: Validation can fail on existing rows; captured statistics do not provide a duration\.
- Limitation: Foreign\-key binding requires the referenced table scope\.
- Limitation: Confirmed constraint effects require a supported ordinary relation\.

## Notices and limitations

- The report compares supplied\/observed schema states; migration SQL is secondary requested evidence and is never executed or used to predict an after snapshot\.
- Risk is policy, not a calibrated duration or proof of safety\.
- Reader ownership, uncaptured dependencies and calibrated estimatedSeconds are unavailable in M4\.
