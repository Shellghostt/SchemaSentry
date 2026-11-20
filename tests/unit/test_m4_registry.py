"""Offline public metadata and committed generated documentation agree."""

import subprocess
import sys
from pathlib import Path

from schemasentry.registry import public_rules

ROOT = Path(__file__).parents[2]


def test_ten_public_rules_have_evidence_caveats_and_postgres_references():
    rules = public_rules()
    assert [rule.rule_id for rule in rules] == [f"SS{number:03d}" for number in range(1, 11)]
    assert all(
        rule.evidence_requirements and rule.limitations and rule.references for rule in rules
    )
    assert all(
        reference.startswith("https://www.postgresql.org/docs/16/")
        for rule in rules
        for reference in rule.references
    )


def test_public_documentation_and_schemas_have_no_generated_drift():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_docs.py"), "--check"],
        capture_output=True,
        timeout=20,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
