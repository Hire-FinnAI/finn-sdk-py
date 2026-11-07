#!/usr/bin/env python3
"""Spec drift check: compares the operations this SDK covers with the API's OpenAPI spec. Standard library only.

    python scripts/check_drift.py                          # against https://api.hirefinn.ai/v1/openapi.json
    python scripts/check_drift.py --spec spec/openapi.json # or a file / another URL

The SDK's operations are the resource methods scripts/generate.py builds (RESOURCES plus the generated ones),
resolved through the vendored spec/openapi.json. The SDK must cover every operation, so this fails (exit 1) when:
  - the spec has an operation with no SDK method (a new endpoint: pull the spec and regenerate),
  - the SDK covers an operation the spec no longer has (a removed endpoint).
There is no allow-list of uncovered operations. Path parameter names are ignored ({id} and {call_uuid} compare
equal).
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
from generate import build_resources  # noqa: E402


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
    for op_id in _op_ids(build_resources(vendored)):
        if op_id not in by_id:
            raise SystemExit(f"RESOURCES names {op_id}, which spec/openapi.json does not have")
        out[norm(by_id[op_id])] = by_id[op_id]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", default=os.environ.get("FINN_SPEC", DEFAULT_SPEC))
    args = ap.parse_args()

    live = spec_ops(load_spec(args.spec))
    sdk = sdk_ops(json.loads((ROOT / "spec" / "openapi.json").read_text(encoding="utf-8")))
    uncovered = [v for k, v in live.items() if k not in sdk]
    removed = [v for k, v in sdk.items() if k not in live]

    print(f"Spec {args.spec}: {len(live)} operations. SDK covers {len(live) - len(uncovered)}.")
    for title, items in (
        ("In the spec, not in the SDK", uncovered),
        ("Covered by the SDK but gone from the spec", removed),
    ):
        if items:
            print(f"\n{title} ({len(items)}):", file=sys.stderr)
            for v in sorted(items):
                print(f"  {v}", file=sys.stderr)

    if uncovered or removed:
        print("\nSpec drift found. Run scripts/pull-spec.sh (or scripts/generate.py <url>) to regenerate, then rerun.",
              file=sys.stderr)
        return 1
    print("No drift: the SDK covers every operation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
