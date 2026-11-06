#!/usr/bin/env python3
"""Spec drift check: compares the operations this SDK covers with the API's OpenAPI spec. Standard library only.

    python scripts/check_drift.py                          # against https://api.hirefinn.ai/v1/openapi.json
    python scripts/check_drift.py --spec spec/openapi.json # or a file / another URL
    python scripts/check_drift.py --write-baseline         # accept today's uncovered ops into spec/uncovered-ops.json

The SDK's operations are the RESOURCES entries in scripts/generate.py, resolved through the vendored
spec/openapi.json. Fails (exit 1) when:
  - the spec has an operation the SDK neither covers nor lists in spec/uncovered-ops.json (a new endpoint),
  - the SDK covers an operation the spec no longer has (a removed endpoint),
  - spec/uncovered-ops.json lists an operation that is gone from the spec or that the SDK now covers.
Path parameter names are ignored ({id} and {call_uuid} compare equal).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = "https://api.hirefinn.ai/v1/openapi.json"
METHODS = ("get", "post", "put", "patch", "delete")

sys.path.insert(0, str(ROOT / "scripts"))
from generate import RESOURCES  # noqa: E402


def norm(op: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", op)


def load_spec(src: str) -> Dict[str, Any]:
    if re.match(r"^https?://", src):
        req = urllib.request.Request(src, headers={"Accept": "application/json", "User-Agent": "finn-sdk-drift"})
        with urllib.request.urlopen(req, timeout=30) as res:  # noqa: S310 (fixed https URL or one passed explicitly)
            return json.loads(res.read().decode("utf-8"))
    return json.loads(Path(src).read_text(encoding="utf-8"))


def spec_ops(spec: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path, item in (spec.get("paths") or {}).items():
        for m in METHODS:
            if isinstance(item, dict) and item.get(m):
                out[norm(f"{m} {path}")] = f"{m} {path}"
    return out


def _op_ids(entries: List[Dict[str, Any]]) -> Iterator[str]:
    for e in entries:
        if "op" in e:
            yield e["op"]
        for key in ("methods", "children"):
            yield from _op_ids(e.get(key, []))


def sdk_ops(vendored: Dict[str, Any]) -> Dict[str, str]:
    by_id: Dict[str, str] = {}
    for path, item in vendored.get("paths", {}).items():
        for m in METHODS:
            if isinstance(item, dict) and item.get(m, {}).get("operationId"):
                by_id[item[m]["operationId"]] = f"{m} {path}"
    out: Dict[str, str] = {}
    for op_id in _op_ids(RESOURCES):
        if op_id not in by_id:
            raise SystemExit(f"RESOURCES names {op_id}, which spec/openapi.json does not have")
        out[norm(by_id[op_id])] = by_id[op_id]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", default=os.environ.get("FINN_SPEC", DEFAULT_SPEC))
    ap.add_argument("--uncovered", default=str(ROOT / "spec" / "uncovered-ops.json"))
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args()

    live = spec_ops(load_spec(args.spec))
    sdk = sdk_ops(json.loads((ROOT / "spec" / "openapi.json").read_text(encoding="utf-8")))
    uncovered_file = Path(args.uncovered)

    if args.write_baseline:
        missing = sorted(v for k, v in live.items() if k not in sdk)
        uncovered_file.write_text(json.dumps(missing, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(missing)} uncovered operations to {uncovered_file}")
        return 0

    uncovered = {norm(v): v for v in json.loads(uncovered_file.read_text(encoding="utf-8"))}
    added = [v for k, v in live.items() if k not in sdk and k not in uncovered]
    removed = [v for k, v in sdk.items() if k not in live]
    stale_gone = [v for k, v in uncovered.items() if k not in live]
    stale_covered = [v for k, v in uncovered.items() if k in sdk]

    print(f"Spec {args.spec}: {len(live)} operations. SDK covers {len(sdk)}; {len(uncovered)} known uncovered.")
    for title, items in (
        ("New in the spec, not in the SDK or spec/uncovered-ops.json", added),
        ("Covered by the SDK but gone from the spec", removed),
        ("In spec/uncovered-ops.json but gone from the spec", stale_gone),
        ("In spec/uncovered-ops.json but now covered by the SDK", stale_covered),
    ):
        if items:
            print(f"\n{title} ({len(items)}):", file=sys.stderr)
            for v in sorted(items):
                print(f"  {v}", file=sys.stderr)

    if added or removed or stale_gone or stale_covered:
        print("\nSpec drift found. Add SDK methods (or list the ops in spec/uncovered-ops.json), then rerun.", file=sys.stderr)
        return 1
    print("No drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
