# 0061-check-not-valid

NOT VALID avoids the initial existing-row validation for a CHECK. The statement still locks and enforces new writes; this negative case does not establish universal safety.

Expected values are independently reviewed policy/evidence assertions, committed before rule implementation.

PostgreSQL reference: [https://www.postgresql.org/docs/16/sql-altertable.html](https://www.postgresql.org/docs/16/sql-altertable.html).
