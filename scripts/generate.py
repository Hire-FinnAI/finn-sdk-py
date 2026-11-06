#!/usr/bin/env python3
"""Regenerates finn/_generated/ from an OpenAPI spec. Standard library only.

    python scripts/generate.py                        # from the vendored spec/openapi.json
    python scripts/generate.py ./path/to/spec.json    # also copies it to spec/openapi.json
    python scripts/generate.py https://example.com/openapi.json

Writes:
  finn/_generated/schemas.py    TypedDicts for every schema, request body, query and response in the spec
  finn/_generated/resources.py  sync + async resource classes (one typed method per operation, per RESOURCES below)
  finn/_generated/request.py    typed overloads of client.request(method, path, ...) for every operation

RESOURCES groups operations the way the TypeScript SDK (finn-sdk-ts/src/resources.ts) does, with Python names.
The script fails if an entry names an operation the spec does not have, and lists spec operations no entry covers
(those stay reachable through client.request()).
"""
from __future__ import annotations

import json
import keyword
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
VENDORED = ROOT / "spec" / "openapi.json"
OUT = ROOT / "finn" / "_generated"

# Writes the API may hold for a person to approve (HTTP 202 pending_approval). Mirrors HoldableRoute in finn-sdk-ts.
HOLDABLE = {"post /calls", "post /deployments", "post /phone_numbers"}

# Writes that get an automatic Idempotency-Key. Mirrors AUTO_IDEMPOTENCY_ROUTES in finn-sdk-ts (kept in finn/_core.py).
AUTO_IDEMPOTENCY_NOTE = {
    "post /calls", "post /phone_numbers", "post /deployments", "post /deployments/inbound",
    "post /chat/conversations", "post /chat/conversations/{id}/messages", "post /agents", "post /agents/{id}/cases",
}


def m(name: str, op: str, **extra: Any) -> Dict[str, Any]:
    return {"name": name, "op": op, **extra}


def pager(name: str, op: str, strategy: str, item: str, *args: str, **extra: Any) -> Dict[str, Any]:
    return {"name": name, "op": op, "pager": (strategy, item, list(args)), **extra}


# (class name, attribute on the client, methods, children)
RESOURCES: List[Dict[str, Any]] = [
    {"cls": "Calls", "attr": "calls", "doc": "Phone calls.", "methods": [
        m("create", "createCall"),
        m("list", "listCalls"),
        pager("list_all", "listCalls", "offset", "CallSummary", "data"),
        m("retrieve", "retrieveCall"),
    ]},
    {"cls": "Finns", "attr": "finns", "doc": "Finns (voice agents).", "methods": [
        m("list", "listFinns"),
        pager("list_all", "listFinns", "offset", "Finn", "data"),
        m("create", "createFinn"),
        m("retrieve", "retrieveFinn"),
        m("update", "updateFinn"),
        m("delete", "deleteFinn"),
        m("list_knowledge_base", "listKnowledgeBase"),
        m("add_knowledge_base_document", "addKnowledgeBaseDocument"),
        m("post_call_analysis", "getFinnPostCallAnalysis"),
    ]},
    {"cls": "Voices", "attr": "voices", "doc": "Voices a Finn can speak with.", "methods": [
        m("list", "listVoices"),
        pager("list_all", "listVoices", "offset", "Voice", "data"),
        m("retrieve", "retrieveVoice"),
    ]},
    {"cls": "PhoneNumbers", "attr": "phone_numbers", "doc": "Phone numbers.", "methods": [
        m("list", "listPhoneNumbers"),
        pager("list_all", "listPhoneNumbers", "offset", "PhoneNumber", "data"),
        m("search_available", "searchAvailablePhoneNumbers"),
        m("rent", "rentPhoneNumber"),
        m("retrieve", "retrievePhoneNumber"),
        m("release", "releasePhoneNumber"),
    ]},
    {"cls": "Audiences", "attr": "audiences", "doc": "Audiences (call lists).", "methods": [
        m("list", "listAudiences"),
        pager("list_all", "listAudiences", "offset", "Audience", "data"),
        m("create", "createAudience"),
        m("retrieve", "retrieveAudience"),
        m("archive", "archiveAudience"),
        m("list_contacts", "listAudienceContacts"),
        pager("list_all_contacts", "listAudienceContacts", "offset", "Contact", "data"),
        m("add_contacts", "addAudienceContacts"),
        m("remove_contact", "removeAudienceContact"),
    ]},
    {"cls": "Deployments", "attr": "deployments", "doc": "Campaigns: outbound and inbound deployments of a Finn.",
     "methods": [
        m("list", "listDeployments"),
        pager("list_all", "listDeployments", "offset", "Deployment", "data"),
        m("create_outbound", "createOutboundDeployment"),
        m("create_inbound", "createInboundDeployment"),
        m("retrieve", "retrieveDeployment"),
        m("stop", "stopDeployment"),
        m("stop_inbound", "stopInboundDeployment"),
        m("analytics", "getDeploymentAnalytics"),
    ]},
    {"cls": "Wallet", "attr": "wallet", "doc": "Credits balance and ledger.", "methods": [
        m("retrieve", "retrieveWallet"),
        m("list_transactions", "listWalletTransactions"),
        pager("list_all_transactions", "listWalletTransactions", "offset", "WalletTransaction", "data"),
    ]},
    {"cls": "DoNotCall", "attr": "do_not_call", "doc": "The org's do-not-call list.", "methods": [
        m("list", "listDoNotCall"),
        pager("list_all", "listDoNotCall", "offset", "DoNotCallEntry", "data"),
        m("add", "addDoNotCall"),
        m("remove", "removeDoNotCall", doc="Needs the `voice:dnc:write` scope."),
    ]},
    {"cls": "Contacts", "attr": "contacts", "doc": "CRM records (contacts and other record kinds).", "methods": [
        m("list", "listRecords"),
        pager("list_all", "listRecords", "page", "Record", "contacts"),
        m("create", "createRecord"),
        m("retrieve", "retrieveRecord"),
        m("update", "updateRecord"),
        m("timeline", "listRecordTimeline"),
        pager("timeline_all", "listRecordTimeline", "before", "TimelineItem", "items", "next"),
        m("add_note", "addRecordNote"),
        m("list_kinds", "listRecordKinds", doc="Record kinds (contact, company, ...)."),
        m("list_fields", "listFields"),
    ]},
    {"cls": "Cases", "attr": "cases", "doc": "Operator cases.", "methods": [
        m("list", "listCases"),
        pager("list_all", "listCases", "before", "CaseSummary", "cases", "next_before"),
        m("retrieve", "retrieveCase"),
        m("list_events", "listCaseEvents"),
        m("start", "startCase", rename={"id": "agent_id"}),
    ]},
    {"cls": "Approvals", "attr": "approvals", "doc": "Operator approvals and held API requests.",
     "mixin": "ApprovalWait", "methods": [
        m("list", "listApprovals"),
        pager("list_all", "listApprovals", "cursor", "Approval", "approvals"),
        m("retrieve", "retrieveApproval", unwrap=True, returns="Union[Approval, ApprovalHold]",
          doc="An Operator approval, or a held API request (`source: 'api_hold'`) made by this caller."),
        m("decide", "decideApproval"),
        m("approve", "approveApproval"),
        m("reject", "rejectApproval"),
    ]},
    {"cls": "Agents", "attr": "agents", "doc": "Operator agents.", "methods": [
        m("list", "listAgents"),
        pager("list_all", "listAgents", "cursor", "AgentSummary", "data"),
        m("create", "createAgent"),
        m("draft", "draftAgent"),
        m("retrieve", "getAgent"),
        m("save_draft", "saveAgentDraft"),
        m("validate", "validateAgent"),
        m("test", "testAgent"),
        m("publish", "publishAgent"),
        m("drive_test", "driveAgentTest", rename={"id": "case_id"}),
    ]},
    {"cls": "Chat", "attr": "chat", "doc": "Chat channels, conversations and contacts.", "methods": [
        m("list_channels", "listChatChannels"),
    ], "children": [
        {"cls": "ChatConversations", "attr": "conversations", "doc": "Chat conversations.", "methods": [
            m("list", "listChatConversations"),
            pager("list_all", "listChatConversations", "cursor", "Dict[str, Any]", "data"),
            m("start", "startChatConversation"),
            m("retrieve", "getChatConversation"),
            m("list_messages", "listChatMessages"),
            pager("list_all_messages", "listChatMessages", "cursor", "Dict[str, Any]", "data"),
            m("send", "sendChatMessage"),
        ]},
        {"cls": "ChatContacts", "attr": "contacts", "doc": "Chat contacts.", "methods": [
            m("list", "listChatContacts"),
            pager("list_all", "listChatContacts", "cursor", "Dict[str, Any]", "data"),
            m("retrieve", "getChatContact"),
            m("update", "updateChatContact"),
        ]},
    ]},
]

METHODS = ("get", "post", "put", "patch", "delete")


# ---------------------------------------------------------------- naming


def pascal(s: str) -> str:
    parts = re.split(r"[^0-9A-Za-z]+", s)
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return out if out and not out[0].isdigit() else "T" + out


def snake(s: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_").lower()
    if keyword.iskeyword(s) or not s.isidentifier():
        s += "_"
    return s


# ---------------------------------------------------------------- schema -> Python types


class TypeGen:
    def __init__(self, spec: Dict[str, Any]):
        self.spec = spec
        self.schemas: Dict[str, Any] = spec.get("components", {}).get("schemas", {})
        self.classes: List[Tuple[str, List[str]]] = []  # TypedDict classes, in emit order
        self.aliases: Dict[str, Tuple[str, set]] = {}  # name -> (expr, deps)
        self.taken = set(self.schemas.keys())
        self.done = set()

    def unique(self, name: str) -> str:
        base, i = name, 2
        while name in self.taken:
            name = f"{base}{i}"
            i += 1
        self.taken.add(name)
        return name

    def resolve(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        while isinstance(schema, dict) and "$ref" in schema:
            schema = self.lookup(schema["$ref"])
        return schema

    def lookup(self, ref: str) -> Dict[str, Any]:
        node: Any = self.spec
        for part in ref.lstrip("#/").split("/"):
            node = node[part]
        return node

    def build_components(self) -> None:
        for name in self.schemas:
            self.named(name, self.schemas[name])

    def named(self, name: str, schema: Dict[str, Any]) -> None:
        """Emits schema under `name`, as a TypedDict when it is an object, else as an alias."""
        if name in self.done:
            return
        self.done.add(name)
        if self.is_object(schema):
            self.typed_dict(name, schema)
        else:
            deps: set = set()
            expr = self.expr(schema, name, deps)
            self.aliases[name] = (expr, deps)

    def is_object(self, schema: Dict[str, Any]) -> bool:
        if "allOf" in schema:
            return all(self.is_object(self.resolve(s)) for s in schema["allOf"])
        t = schema.get("type")
        return (t == "object" or (t is None and "properties" in schema)) and bool(schema.get("properties")) \
            and "oneOf" not in schema and "anyOf" not in schema

    def typed_dict(self, name: str, schema: Dict[str, Any]) -> None:
        bases: List[str] = []
        props: Dict[str, Any] = {}
        required: set = set()
        parts = schema["allOf"] if "allOf" in schema else [schema]
        for part in parts:
            if "$ref" in part:
                ref_name = part["$ref"].split("/")[-1]
                if part["$ref"].startswith("#/components/schemas/"):
                    self.named(ref_name, self.schemas[ref_name])
                    bases.append(ref_name)
                    continue
                part = self.resolve(part)
            props.update(part.get("properties", {}))
            required.update(part.get("required", []))
        if "allOf" in schema and schema.get("properties"):
            props.update(schema["properties"])
            required.update(schema.get("required", []))
        fields_req: List[Tuple[str, str]] = []
        fields_opt: List[Tuple[str, str]] = []
        for key, sub in props.items():
            deps: set = set()
            t = self.expr(sub, name + pascal(key), deps)
            (fields_req if key in required else fields_opt).append((key, t))
        doc = (schema.get("description") or "").strip().splitlines()
        self.emit_class(name, bases, fields_req, fields_opt, doc[0] if doc else "")

    def emit_class(self, name: str, bases: List[str], req, opt, doc: str) -> None:
        valid = all(k.isidentifier() and not keyword.iskeyword(k) for k, _ in list(req) + list(opt))
        lines: List[str] = []
        if not valid:
            # Functional syntax: every key optional, types as strings (forward references).
            body = ", ".join(f"{k!r}: {t!r}" for k, t in list(req) + list(opt))
            lines.append(f"{name} = TypedDict({name!r}, {{{body}}}, total=False)")
            self.classes.append((name, lines))
            return
        base_list = bases or ["TypedDict"]
        if req and opt:
            req_name = f"_{name}Required"
            lines.append(f"class {req_name}({', '.join(base_list)}):")
            lines.extend(f"    {k}: {t}" for k, t in req)
            lines.append("")
            lines.append("")
            lines.append(f"class {name}({req_name}, total=False):")
            if doc:
                lines.append(f"    {json.dumps(doc)}")
            lines.extend(f"    {k}: {t}" for k, t in opt)
        else:
            fields = req or opt
            total = "" if req else ", total=False"
            lines.append(f"class {name}({', '.join(base_list)}{total}):")
            if doc:
                lines.append(f"    {json.dumps(doc)}")
            lines.extend(f"    {k}: {t}" for k, t in fields)
            if not fields and not doc:
                lines.append("    pass")
        self.classes.append((name, lines))

    def expr(self, schema: Any, hint: str, deps: set) -> str:
        if schema is True or schema == {}:
            return "Any"
        if not isinstance(schema, dict):
            return "Any"
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref.startswith("#/components/schemas/"):
                name = ref.split("/")[-1]
                self.named(name, self.schemas[name])
                deps.add(name)
                return name
            return self.expr(self.resolve(schema), hint, deps)
        if "allOf" in schema:
            parts = schema["allOf"]
            if len(parts) == 1 and not schema.get("properties"):
                return self.expr(parts[0], hint, deps)
            if self.is_object(schema):
                name = self.unique(hint)
                self.done.add(name)
                self.typed_dict(name, schema)
                deps.add(name)
                return name
            return "Dict[str, Any]"
        for key in ("oneOf", "anyOf"):
            if key in schema:
                opts = [self.expr(s, f"{hint}{i + 1}" if len(schema[key]) > 1 else hint, deps)
                        for i, s in enumerate(schema[key])]
                return self.union(opts)
        if "const" in schema:
            return f"Literal[{schema['const']!r}]"
        t = schema.get("type")
        types = t if isinstance(t, list) else [t] if t else []
        nullable = "null" in types or schema.get("nullable") is True
        types = [x for x in types if x != "null"]
        if "enum" in schema:
            vals = [v for v in schema["enum"] if v is not None]
            if None in schema["enum"]:
                nullable = True
            out = f"Literal[{', '.join(repr(v) for v in vals)}]" if vals else "None"
            return f"Optional[{out}]" if nullable and vals else out
        if not types:
            if "properties" in schema:
                types = ["object"]
            elif "items" in schema:
                types = ["array"]
            else:
                return "Any"
        exprs = [self.single(x, schema, hint, deps) for x in types]
        out = self.union(exprs)
        return f"Optional[{out}]" if nullable and out != "Any" else out

    def single(self, t: str, schema: Dict[str, Any], hint: str, deps: set) -> str:
        if t == "string":
            return "str"
        if t == "integer":
            return "int"
        if t == "number":
            return "float"
        if t == "boolean":
            return "bool"
        if t == "array":
            return f"List[{self.expr(schema.get('items', {}), hint + 'Item', deps)}]"
        if t == "object":
            if schema.get("properties") and "oneOf" not in schema and "anyOf" not in schema:
                name = self.unique(hint)
                self.done.add(name)
                self.typed_dict(name, schema)
                deps.add(name)
                return name
            ap = schema.get("additionalProperties")
            if isinstance(ap, dict) and ap:
                return f"Dict[str, {self.expr(ap, hint + 'Value', deps)}]"
            return "Dict[str, Any]"
        return "Any"

    @staticmethod
    def union(opts: List[str]) -> str:
        seen: List[str] = []
        for o in opts:
            if o not in seen:
                seen.append(o)
        if "Any" in seen:
            return "Any"
        return seen[0] if len(seen) == 1 else f"Union[{', '.join(seen)}]"

    def render(self) -> str:
        out = [
            '"""Generated by scripts/generate.py from spec/openapi.json. Do not edit by hand."""',
            "# fmt: off",
            "# ruff: noqa",
            "from __future__ import annotations",
            "",
            "from typing import Any, Dict, List, Optional, Union",
            "",
            "from .._compat import Literal, TypedDict",
            "",
        ]
        for _, lines in self.classes:
            out.append("")
            out.extend(lines)
            out.append("")
        # Aliases are evaluated at import time: emit them after every class, in dependency order.
        emitted: set = set()

        def emit(name: str, stack: set) -> None:
            if name in emitted or name not in self.aliases or name in stack:
                return
            expr, deps = self.aliases[name]
            for d in sorted(deps):
                emit(d, stack | {name})
            out.append(f"{name} = {expr}")
            emitted.add(name)

        if self.aliases:
            out.append("")
            for name in self.aliases:
                emit(name, set())
        out.append("")
        return "\n".join(out)


# ---------------------------------------------------------------- operations


class Op:
    def __init__(self, gen: TypeGen, method: str, path: str, op: Dict[str, Any], common: List[Any]):
        self.method, self.path, self.raw = method, path, op
        self.op_id = op.get("operationId") or snake(f"{method}_{path}")
        self.summary = (op.get("summary") or "").strip()
        base = pascal(self.op_id)
        params = [gen.resolve(p) for p in common + op.get("parameters", [])]
        self.path_params = [p for p in params if p["in"] == "path"]
        order = re.findall(r"\{([^}]+)\}", path)
        self.path_params.sort(key=lambda p: order.index(p["name"]) if p["name"] in order else 99)
        self.query = []
        for p in params:
            if p["in"] != "query":
                continue
            deps: set = set()
            self.query.append((p["name"], gen.expr(p.get("schema", {}), base + pascal(p["name"]), deps),
                               bool(p.get("required"))))
        self.headers = [p for p in params if p["in"] == "header" and p["name"].lower() != "idempotency-key"]
        rb = op.get("requestBody")
        if rb and "$ref" in rb:
            rb = gen.resolve(rb)
        self.body_type: Optional[str] = None
        self.body_required = False
        self.multipart = False
        if rb:
            content = rb.get("content", {})
            self.multipart = "multipart/form-data" in content
            schema = (content.get("application/json") or content.get("multipart/form-data") or {}).get("schema", {})
            deps = set()
            self.body_type = gen.expr(schema, base + "Body", deps)
            if self.body_type in ("Any",):
                self.body_type = "Dict[str, Any]"
            self.body_required = bool(rb.get("required")) and not self.multipart
        resp_types: List[str] = []
        ok = sorted(k for k in op.get("responses", {}) if str(k).startswith("2"))
        for code in ok:
            r = op["responses"][code]
            if "$ref" in r:
                r = gen.resolve(r)
            schema = r.get("content", {}).get("application/json", {}).get("schema")
            if schema is None:
                resp_types.append("None" if str(code) == "204" else "Any")
                continue
            hint = base + "Response" + ("" if len(ok) == 1 else str(code))
            resp_types.append(gen.expr(schema, hint, set()))
        self.response = TypeGen.union(resp_types) if resp_types else "Dict[str, Any]"
        self.route = f"{method} {path}"
        self.holdable = self.route in HOLDABLE
        self.auto_key = self.route in AUTO_IDEMPOTENCY_NOTE

    @property
    def result(self) -> str:
        return f"Union[{self.response}, PendingApproval]" if self.holdable else self.response


def load_ops(gen: TypeGen) -> Dict[str, Op]:
    ops: Dict[str, Op] = {}
    for path, item in gen.spec.get("paths", {}).items():
        common = item.get("parameters", [])
        for method in METHODS:
            if method in item:
                op = Op(gen, method, path, item[method], common)
                ops[op.op_id] = op
    return ops


_TOKEN = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\b[A-Za-z_]\w*\b")
SCHEMA_NAMES: set = set()


def q(expr: str) -> str:
    """Prefixes schema names with `t.` so they cannot clash with resource class names (e.g. Wallet)."""
    return _TOKEN.sub(lambda mt: "t." + mt.group(0) if mt.group(0) in SCHEMA_NAMES else mt.group(0), expr)


OPTION_PARAMS = [
    ("idempotency_key", "Union[str, bool, None]", "None"),
    ("org", "Optional[str]", "None"),
    ("version", "Optional[str]", "None"),
    ("max_retries", "Optional[int]", "None"),
    ("timeout", "Optional[float]", "None"),
    ("extra_headers", "Optional[Mapping[str, str]]", "None"),
]
OPTION_PASS = ", ".join(f"{n}={n}" for n, _, _ in OPTION_PARAMS)


def signature(op: Op, rename: Dict[str, str], with_body: bool = True) -> Tuple[List[str], List[str], Dict[str, str]]:
    """(positional params, keyword-only params, query wire-name -> python-name)."""
    pos = [f"{rename.get(p['name'], snake(p['name']))}: str" for p in op.path_params]
    if with_body and op.body_type:
        if op.body_required:
            pos.append(f"body: {q(op.body_type)}")
        else:
            pos.append(f"body: Optional[{q(op.body_type)}] = None")
    kw: List[str] = []
    qmap: Dict[str, str] = {}
    for wire, t, req in op.query:
        py = snake(wire)
        qmap[wire] = py
        kw.append(f"{py}: {q(t)}" if req else f"{py}: Optional[{q(t)}] = None")
    if with_body and op.multipart:
        kw.append("files: Optional[Mapping[str, Any]] = None")
    for h in op.headers:
        kw.append(f"{snake(h['name'])}: Optional[str] = None")
    return pos, kw, qmap


def method_doc(op: Op, extra: Optional[str]) -> List[str]:
    lines = [f"{op.summary or op.op_id}" + ("" if (op.summary or "").endswith(".") else ".")]
    lines.append("")
    lines.append(f"``{op.method.upper()} {op.path}`` ({op.op_id}).")
    if extra:
        lines.append(extra)
    if op.auto_key:
        lines.append("Gets an automatic Idempotency-Key, so it is safe to retry.")
    if op.holdable:
        lines.append("May answer a PendingApproval (HTTP 202) instead of doing the work; see is_pending_approval().")
    return lines


def render_resources(gen: TypeGen, ops: Dict[str, Op]) -> str:
    used_types: set = set()
    out_sync: List[str] = []
    out_async: List[str] = []

    def emit(res: Dict[str, Any], is_async: bool, out: List[str]) -> None:
        for child in res.get("children", []):
            emit(child, is_async, out)
        prefix = "Async" if is_async else ""
        mixin = res.get("mixin")
        bases = ([f"{prefix}{mixin}"] if mixin else []) + [f"{prefix}Resource"]
        out.append("")
        out.append("")
        out.append(f"class {prefix}{res['cls']}({', '.join(bases)}):")
        out.append(f'    """{res["doc"]}"""')
        out.append("")
        children = res.get("children", [])
        if children:
            out.append(f"    def __init__(self, core: {'AsyncCore' if is_async else 'SyncCore'}) -> None:")
            out.append("        super().__init__(core)")
            for child in children:
                out.append(f"        self.{child['attr']} = {prefix}{child['cls']}(core)")
            out.append("")
        for spec in res["methods"]:
            op = ops[spec["op"]]
            rename = spec.get("rename", {})
            is_pager = "pager" in spec
            pos, kw, qmap = signature(op, rename, with_body=not is_pager)
            args = ["self"] + pos
            if kw or OPTION_PARAMS:
                args.append("*")
                args += kw
                args += [f"{n}: {t} = {d}" for n, t, d in OPTION_PARAMS]
            path_args = ", ".join(f"{p['name']!r}: {rename.get(p['name'], snake(p['name']))}" for p in op.path_params)
            query = ", ".join(f"{w!r}: {py}" for w, py in qmap.items())
            hdrs = ", ".join(f"{h['name']!r}: {snake(h['name'])}" for h in op.headers)
            if is_pager:
                strategy, item, sargs = spec["pager"]
                used_types.add(item)
                ret = f"{'Async' if is_async else 'Sync'}Paginator[{q(item)}]"
                out.append(f"    def {spec['name']}({', '.join(args)}) -> {ret}:")
                doc = [f"Every item of {op.op_id}, fetching pages as you iterate ({strategy} pagination)."]
            else:
                ret = q(spec.get("returns") or op.result)
                out.append(f"    {'async ' if is_async else ''}def {spec['name']}({', '.join(args)}) -> {ret}:")
                doc = method_doc(op, spec.get("doc"))
            out.append('        """' + doc[0])
            for line in doc[1:]:
                out.append(f"        {line}" if line else "")
            out.append('        """')
            if is_pager:
                sargs_s = ", ".join(repr(a) for a in sargs)
                out.append(f"        return self._pager(")
                out.append(f"            {op.path!r}, {strategy}_strategy({sargs_s}),")
                out.append(f"            path_params={{{path_args}}}, query={{{query}}},")
                out.append(f"            {OPTION_PASS},")
                out.append("        )")
            else:
                aw = "await " if is_async else ""
                out.append(f"        return {aw}self._do(  # type: ignore[no-any-return]")
                out.append(f"            {op.method!r}, {op.path!r},")
                out.append(f"            path_params={{{path_args}}}, query={{{query}}},")
                if op.body_type:
                    out.append("            body=body,")
                if op.multipart:
                    out.append("            files=files,")
                if hdrs:
                    out.append(f"            headers={{{hdrs}}},")
                if spec.get("unwrap"):
                    out.append("            unwrap=True,")
                out.append(f"            {OPTION_PASS},")
                out.append("        )")
            out.append("")

    for res in RESOURCES:
        emit(res, False, out_sync)
    for res in RESOURCES:
        emit(res, True, out_async)

    header = [
        '"""Generated by scripts/generate.py from spec/openapi.json. Do not edit by hand."""',
        "# fmt: off",
        "# ruff: noqa",
        "from __future__ import annotations",
        "",
        "from typing import Any, Dict, List, Mapping, Optional, Union",
        "",
        "from .._approval import ApprovalWait, AsyncApprovalWait, PendingApproval",
        "from .._compat import Literal",
        "from .._core import AsyncCore, SyncCore",
        "from .._pagination import (",
        "    AsyncPaginator,",
        "    SyncPaginator,",
        "    before_strategy,",
        "    cursor_strategy,",
        "    offset_strategy,",
        "    page_strategy,",
        ")",
        "from .._resource import AsyncResource, Resource",
        "from .._types import ApprovalHold",
        "from . import schemas as t",
        "",
        "__all__ = [" + ", ".join(repr(n) for n in all_classes()) + "]",
    ]
    return "\n".join(header + out_sync + out_async) + "\n"


def all_classes() -> List[str]:
    names: List[str] = []

    def walk(res: Dict[str, Any]) -> None:
        for c in res.get("children", []):
            walk(c)
        names.append(res["cls"])

    for r in RESOURCES:
        walk(r)
    return names + ["Async" + n for n in names]


def render_request(ops: Dict[str, Op]) -> str:
    """Typed overloads of request(method, path, ...) for every operation in the spec."""
    out_s: List[str] = []
    out_a: List[str] = []
    for op in ops.values():
        for is_async, out in ((False, out_s), (True, out_a)):
            pp = "path_params: Mapping[str, str]" if op.path_params else "path_params: None = None"
            body = ""
            if op.body_type:
                body = f"body: {q(op.body_type)}" if op.body_required else f"body: Optional[{q(op.body_type)}] = None"
            else:
                body = "body: None = None"
            parts = [f"method: Literal[{op.method!r}]", f"path: Literal[{op.path!r}]", "*", pp, body,
                     "query: Optional[Mapping[str, Any]] = None", "**options: Any"]
            out.append("    @overload")
            out.append(f"    {'async ' if is_async else ''}def request(self, {', '.join(parts)}) -> {q(op.result)}: ...")
    impl = (
        "    def request(self, method: str, path: str, **kwargs: Any) -> Any:\n"
        '        """Calls any operation in the spec, typed by (method, path). For paths newer than this SDK, use\n'
        '        raw_request()."""\n'
        "        return self._request_data(method, path, **kwargs)\n"
    )
    impl_a = (
        "    async def request(self, method: str, path: str, **kwargs: Any) -> Any:\n"
        '        """Calls any operation in the spec, typed by (method, path). For paths newer than this SDK, use\n'
        '        raw_request()."""\n'
        "        return await self._request_data(method, path, **kwargs)\n"
    )
    head = [
        '"""Generated by scripts/generate.py from spec/openapi.json. Do not edit by hand."""',
        "# fmt: off",
        "# ruff: noqa",
        "from __future__ import annotations",
        "",
        "from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Union, overload",
        "",
        "from .._approval import PendingApproval",
        "from .._compat import Literal",
        "from . import schemas as t",
        "",
        "",
        "class TypedRequest:",
        '    """Mixin for the sync client."""',
        "",
        "    if TYPE_CHECKING:",
        "        def _request_data(self, method: str, path: str, **kwargs: Any) -> Any: ...",
        "",
    ]
    mid = ["", "", "class AsyncTypedRequest:", '    """Mixin for the async client."""', "",
           "    if TYPE_CHECKING:",
           "        async def _request_data(self, method: str, path: str, **kwargs: Any) -> Any: ...", ""]
    return "\n".join(head + out_s + [impl] + mid + out_a + [impl_a])


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else str(VENDORED)
    if re.match(r"^https?://", source):
        with urllib.request.urlopen(source) as r:  # noqa: S310 (caller-supplied spec URL)
            text = r.read().decode("utf-8")
    else:
        text = Path(source).read_text("utf-8")
    spec = json.loads(text)
    is_url = bool(re.match(r"^https?://", source))
    if is_url or Path(source).resolve() != VENDORED.resolve():
        VENDORED.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"Copied spec to {VENDORED}")

    gen = TypeGen(spec)
    gen.build_components()
    ops = load_ops(gen)
    SCHEMA_NAMES.update(name for name, _ in gen.classes)
    SCHEMA_NAMES.update(gen.aliases)

    mapped = set()
    missing = []

    def check(res: Dict[str, Any]) -> None:
        for c in res.get("children", []):
            check(c)
        for spec_m in res["methods"]:
            if spec_m["op"] not in ops:
                missing.append(f"{res['cls']}.{spec_m['name']} -> {spec_m['op']}")
            mapped.add(spec_m["op"])

    for r in RESOURCES:
        check(r)
    if missing:
        sys.exit("RESOURCES names operations the spec does not have:\n  " + "\n  ".join(missing))
    unmapped = [f"{o.method.upper()} {o.path} ({o.op_id})" for o in ops.values() if o.op_id not in mapped]

    resources = render_resources(gen, ops)
    request = render_request(ops)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "schemas.py").write_text(gen.render(), "utf-8")
    (OUT / "resources.py").write_text(resources, "utf-8")
    (OUT / "request.py").write_text(request, "utf-8")
    (OUT / "__init__.py").write_text(
        '"""Generated code. Do not edit by hand: run `python scripts/generate.py`."""\n'
        f"SPEC_TITLE = {spec.get('info', {}).get('title')!r}\n"
        f"SPEC_VERSION = {spec.get('info', {}).get('version')!r}\n"
        f"OPERATION_COUNT = {len(ops)}\n",
        "utf-8",
    )
    print(f"Wrote {OUT}: {len(gen.classes)} TypedDicts, {len(gen.aliases)} aliases, {len(ops)} operations")
    if unmapped:
        print("Not in RESOURCES (use client.request()):\n  " + "\n  ".join(unmapped))


if __name__ == "__main__":
    main()
