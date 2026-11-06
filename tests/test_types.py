"""Type checks (the TS suite's `types` case): mypy must accept typecheck_sample.py, including every expected error."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_resource_methods_return_spec_types():
    pytest.importorskip("mypy")
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-incremental", "--warn-unused-ignores", "--show-error-codes",
         "--config-file", str(ROOT / "pyproject.toml"), str(ROOT / "tests" / "typecheck_sample.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
