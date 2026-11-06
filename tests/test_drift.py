"""scripts/check_drift.py: fails on new or removed endpoints compared with the spec."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDORED = json.loads((ROOT / "spec" / "openapi.json").read_text())
UNCOVERED = json.loads((ROOT / "spec" / "uncovered-ops.json").read_text())


def full_spec():
    """The vendored spec plus every op listed as uncovered: the live spec as it was when the baseline was taken."""
    spec = copy.deepcopy(VENDORED)
    for op in UNCOVERED:
        method, path = op.split(" ", 1)
        spec["paths"].setdefault(path, {})[method] = {"responses": {}}
    return spec


def run(spec, tmp_path):
    f = tmp_path / "openapi.json"
    f.write_text(json.dumps(spec))
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_drift.py"), "--spec", str(f)],
        capture_output=True, text=True, cwd=ROOT,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_passes_when_the_spec_matches_the_sdk_plus_the_uncovered_list(tmp_path):
    code, out = run(full_spec(), tmp_path)
    assert code == 0, out


def test_fails_on_a_new_endpoint(tmp_path):
    spec = full_spec()
    spec["paths"]["/brand_new"] = {"get": {"responses": {}}}
    code, out = run(spec, tmp_path)
    assert code == 1
    assert "get /brand_new" in out.split("New in the spec")[1]


def test_fails_on_a_removed_endpoint_ignoring_path_param_names(tmp_path):
    spec = full_spec()
    del spec["paths"]["/wallet"]
    spec["paths"]["/calls/{id}"] = spec["paths"].pop("/calls/{call_uuid}")
    code, out = run(spec, tmp_path)
    assert code == 1
    assert "get /wallet" in out.split("gone from the spec")[1]
    assert "{call_uuid}" not in out
