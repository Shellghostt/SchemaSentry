"""Exercise the installed module boundary, including wire bytes and schema."""

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
CASES = sorted((ROOT / "tests" / "fixtures").glob("*/before.json"))


@pytest.mark.parametrize("before", CASES, ids=lambda path: path.parent.name)
def test_diff_process(before: Path) -> None:
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "schemasentry",
            "diff",
            "--before",
            str(before),
            "--after",
            str(before.with_name("after.json")),
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert process.returncode == 0
    assert process.stderr == b""
    expected = json.loads(before.with_name("expected.json").read_text(encoding="utf-8"))
    assert process.stdout == (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode()
    schema = json.loads((ROOT / "docs" / "schema" / "diff-v1.schema.json").read_text())
    jsonschema.validate(json.loads(process.stdout), schema)
