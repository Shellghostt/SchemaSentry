# SchemaSentry assessment

Report v1; policy v1; tool 0\.1\.0.

Analysis: **incomplete**; overall risk: **high**; threshold: **high**.

This is an observed-state assessment, with requested SQL evidence. It does not predict or apply a migration.

Before: snapshot v1, catalog evidence 1, postgres 16\.4, capture &lt;b&gt;x&lt;\/b&gt; \[link\]\(https\:\/\/evil\.invalid\) \| \`\`\`\\u000a\# forged\\u202e &#x27; &amp;; digest afdfc5546bef3a94903e8a8b6756eab81f56f26aca332045720d72a79fa0a225.

After: snapshot v1, catalog evidence 1, postgres 16\.4, capture 2026\-11\-17T00\:00\:00Z; digest 5d570ffc1ff397593d7f3fc239022e04270ca5741c3edbbb4f2264f3726135cd.

## SS008: constraint\_validation\_requested

Object: &lt;b&gt;x&lt;\/b&gt; \[link\]\(https\:\/\/evil\.invalid\) \| \`\`\`\\u000a\# forged\\u202e &#x27; &amp; / users / &lt;b&gt;x&lt;\/b&gt; \[link\]\(https\:\/\/evil\.invalid\) \| \`\`\`\\u000a\# forged\\u202e &#x27; &amp;.

Base severity: **high**; final risk: **high**; confidence: **low**.

Effects: unavailable.

- Evidence (migration): &lt;b&gt;x&lt;\/b&gt; \[link\]\(https\:\/\/evil\.invalid\) \| \`\`\`\\u000a\# forged\\u202e &#x27; &amp;

- Modifier row_estimate: not_applied, +0; value 0. Catalog rowEstimate is an estimate; mutually exclusive strict size tiers apply\.
- Modifier incoming_foreign_keys: not_applied, +0; value 0. Distinct incoming named FK constraints target this captured table, including outside\-schema sources when known\.
- Modifier service_reader_lock: unknown, +0; value unavailable. Reader ownership is unavailable under rename\-hints v1\.

Estimated seconds: unavailable.

Alternative: unavailable.

- Limitation: &lt;b&gt;x&lt;\/b&gt; \[link\]\(https\:\/\/evil\.invalid\) \| \`\`\`\\u000a\# forged\\u202e &#x27; &amp;

## Notices and limitations

- unsupported\_evidence [incomplete] (line 1, column 1): &lt;b&gt;x&lt;\/b&gt; \[link\]\(https\:\/\/evil\.invalid\) \| \`\`\`\\u000a\# forged\\u202e &#x27; &amp;
- The report compares supplied\/observed schema states; migration SQL is secondary requested evidence and is never executed or used to predict an after snapshot\.
- Risk is policy, not a calibrated duration or proof of safety\.
- Reader ownership, uncaptured dependencies and calibrated estimatedSeconds are unavailable in M4\.
