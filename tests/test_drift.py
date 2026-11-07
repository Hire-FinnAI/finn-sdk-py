"""scripts/check_drift.py: fails on any spec operation the SDK does not cover, and on removed endpoints."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDORED = json.loads((ROOT / "spec" / "openapi.json").read_text())


def run(spec, tmp_path):
    f = tmp_path / "openapi.json"
    f.write_text(json.dumps(spec))
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_drift.py"), "--spec", str(f)],
        capture_output=True, text=True, cwd=ROOT,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_passes_when_the_sdk_covers_every_operation(tmp_path):
    code, out = run(VENDORED, tmp_path)
    assert code == 0, out
    assert "No drift" in out


def test_there_is_no_uncovered_allow_list():
    assert not (ROOT / "spec" / "uncovered-ops.json").exists()


def test_fails_on_any_uncovered_operation(tmp_path):
    spec = copy.deepcopy(VENDORED)
    spec["paths"]["/brand_new"] = {"get": {"responses": {}}}
    spec["paths"]["/crm/records"]["delete"] = {"responses": {}}
    code, out = run(spec, tmp_path)
    assert code == 1
    section = out.split("In the spec, not in the SDK")[1]
    assert "get /brand_new" in section
    assert "delete /crm/records" in section


def test_fails_on_a_removed_endpoint_ignoring_path_param_names(tmp_path):
    spec = copy.deepcopy(VENDORED)
    del spec["paths"]["/wallet"]
    spec["paths"]["/calls/{id}"] = spec["paths"].pop("/calls/{call_uuid}")
    code, out = run(spec, tmp_path)
    assert code == 1
    assert "get /wallet" in out.split("gone from the spec")[1]
    assert "{call_uuid}" not in out


def test_generator_fails_when_a_spec_operation_has_no_method(tmp_path):
    spec = copy.deepcopy(VENDORED)
    spec["paths"]["/brand_new"] = {"get": {"operationId": "getBrandNew", "responses": {}}}
    f = tmp_path / "openapi.json"
    f.write_text(json.dumps(spec))
    gen = ROOT / "scripts" / "generate.py"
    # Run a copy of the generator against a scratch tree so the real finn/_generated and spec/ are untouched.
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    (work / "spec").mkdir()
    (work / "scripts" / "generate.py").write_text(gen.read_text())
    proc = subprocess.run([sys.executable, str(work / "scripts" / "generate.py"), str(f)],
                          capture_output=True, text=True, cwd=work)
    assert proc.returncode != 0
    assert "getBrandNew" in proc.stderr
