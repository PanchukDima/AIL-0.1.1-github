"""Strict schema, type, effect, CFG and SSA dominance validation."""
import json
import re
from pathlib import Path


class AILError(ValueError):
    pass


TYPES = {"i64", "i1", "ptr"}
EFFECTS = {"io", "unsafe"}
ARITH = {"add", "sub", "mul", "sdiv", "srem"}
BITS = {"and", "or", "xor"}
CMPS = {"eq", "ne", "slt", "sle", "sgt", "sge"}
NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z", re.ASCII)


def fail(where, message):
    raise AILError(f"{where}: {message}")


def shape(obj, required, where, optional=()):
    if not isinstance(obj, dict):
        fail(where, "expected object")
    missing = set(required) - obj.keys()
    extra = obj.keys() - set(required) - set(optional)
    if missing:
        fail(where, f"missing fields: {', '.join(sorted(missing))}")
    if extra:
        fail(where, f"unknown fields: {', '.join(sorted(extra))}")


def array(obj, where):
    if not isinstance(obj, list):
        fail(where, "expected array")
    return obj


def name(value, where):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        fail(where, "expected identifier [A-Za-z_][A-Za-z_0-9]*")
    return value


def typename(value, where):
    if not isinstance(value, str) or value not in TYPES:
        fail(where, "expected type i64, i1 or ptr")
    return value


def typed_params(params, where):
    array(params, where)
    for p in params:
        shape(p, {"id", "type"}, where)
        name(p["id"], where)
        typename(p["type"], where)


def unique(items, where):
    result = {}
    for obj in items:
        key = obj["id"]
        if key in result:
            fail(where, f"duplicate id {key}")
        result[key] = obj
    return result


def load(path):
    def no_duplicates(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise AILError(f"JSON: duplicate key {k}")
            result[k] = v
        return result

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          object_pairs_hook=no_duplicates)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise AILError(f"invalid JSON: {exc}") from exc


def verify(module):
    shape(module, {"version", "entry", "globals", "functions"}, "module")
    if type(module["version"]) is not int or module["version"] != 1:
        fail("module", "unsupported version (expected 1)")
    name(module["entry"], "entry")
    array(module["globals"], "globals")
    for g in module["globals"]:
        shape(g, {"id", "text"}, "global")
        name(g["id"], "global")
        if not isinstance(g["text"], str):
            fail(g["id"], "text must be a string")
        try:
            g["text"].encode("utf-8")
        except UnicodeError:
            fail(g["id"], "text is not valid UTF-8")
    globals_ = unique(module["globals"], "globals")
    array(module["functions"], "functions")
    for f in module["functions"]:
        shape(f, {"id", "params", "return", "effects", "blocks"}, "function")
        name(f["id"], "function")
        typed_params(f["params"], f["id"])
        if len(f["params"]) > 6:
            fail(f["id"], "at most six function arguments supported")
        typename(f["return"], f["id"])
        array(f["effects"], f["id"])
        if any(not isinstance(e, str) or e not in EFFECTS for e in f["effects"]):
            fail(f["id"], "effects may only be io and unsafe")
        if len(set(f["effects"])) != len(f["effects"]):
            fail(f["id"], "duplicate effect")
        array(f["blocks"], f["id"])
        if not f["blocks"]:
            fail(f["id"], "function requires an entry block")
    functions = unique(module["functions"], "functions")
    entry = functions.get(module["entry"])
    if entry is None or entry["params"] or entry["return"] != "i64":
        fail("entry", "must refer to a zero-argument function returning i64")
    for f in functions.values():
        verify_function(f, functions, globals_)
    return module


def verify_function(f, functions, globals_):
    fid = f["id"]
    for b in f["blocks"]:
        shape(b, {"id", "params", "instructions", "term"}, fid)
        name(b["id"], fid)
        typed_params(b["params"], f"{fid}/{b['id']}")
        array(b["instructions"], fid)
    blocks = unique(f["blocks"], fid)
    entry = f["blocks"][0]["id"]
    if blocks[entry]["params"]:
        fail(fid, "entry block cannot have block parameters")
    defs = {}

    def define(value_id, typ, block, index):
        name(value_id, fid)
        typename(typ, fid)
        if value_id in defs:
            fail(fid, f"duplicate SSA value {value_id}")
        defs[value_id] = (typ, block, index)

    for p in f["params"]:
        define(p["id"], p["type"], None, -1)
    for bid, b in blocks.items():
        for p in b["params"]:
            define(p["id"], p["type"], bid, -1)
        for i, ins in enumerate(b["instructions"]):
            if not isinstance(ins, dict) or not {"id", "op", "type"} <= ins.keys():
                fail(f"{fid}/{bid}/{i}", "instruction requires id, op, type")
            define(ins["id"], ins["type"], bid, i)

    succ = {bid: [] for bid in blocks}
    for bid, b in blocks.items():
        t = b["term"]
        where = f"{fid}/{bid}/term"
        if not isinstance(t, dict) or not isinstance(t.get("op"), str):
            fail(where, "terminator requires op")
        if t["op"] == "ret":
            shape(t, {"op", "value"}, where)
            edges = []
        elif t["op"] == "jump":
            shape(t, {"op", "target", "args"}, where)
            edges = [{"target": t["target"], "args": t["args"]}]
        elif t["op"] == "branch":
            shape(t, {"op", "cond", "then", "else"}, where)
            edges = [t["then"], t["else"]]
        else:
            fail(where, "expected ret, jump or branch")
        for edge in edges:
            shape(edge, {"target", "args"}, where)
            target = name(edge["target"], where)
            array(edge["args"], where)
            if target not in blocks:
                fail(where, f"unknown target {target}")
            if target == entry:
                fail(where, "edges to the function entry block are forbidden")
            if len(edge["args"]) != len(blocks[target]["params"]):
                fail(where, f"wrong argument count for block {target}")
            succ[bid].append(target)

    reached = set()
    todo = [entry]
    while todo:
        bid = todo.pop()
        if bid not in reached:
            reached.add(bid)
            todo.extend(succ[bid])
    if reached != blocks.keys():
        fail(fid, f"unreachable blocks: {', '.join(sorted(blocks.keys() - reached))}")
    pred = {bid: set() for bid in blocks}
    for bid, targets in succ.items():
        for target in targets:
            pred[target].add(bid)
    dom = {bid: ({entry} if bid == entry else set(blocks)) for bid in blocks}
    changed = True
    while changed:
        changed = False
        for bid in blocks:
            if bid == entry:
                continue
            new = {bid} | set.intersection(*(dom[p] for p in pred[bid]))
            if new != dom[bid]:
                dom[bid] = new
                changed = True

    def use(value, bid, index, expected=None):
        where = f"{fid}/{bid}/{index}"
        name(value, where)
        if value not in defs:
            fail(where, f"undefined value {value}")
        typ, defining_block, defining_index = defs[value]
        if defining_block == bid and defining_index >= index:
            fail(where, f"value {value} used before definition")
        if defining_block is not None and defining_block not in dom[bid]:
            fail(where, f"definition of {value} does not dominate use")
        if expected is not None and typ != expected:
            fail(where, f"{value} has type {typ}, expected {expected}")
        return typ

    def effect(required, where):
        if not set(required) <= set(f["effects"]):
            fail(where, f"requires declared effects: {', '.join(sorted(required))}")

    for bid, b in blocks.items():
        for i, ins in enumerate(b["instructions"]):
            where = f"{fid}/{bid}/{ins['id']}"
            op, typ = ins["op"], ins["type"]
            base = {"id", "op", "type"}
            if not isinstance(op, str):
                fail(where, "op must be a string")
            if op == "const":
                shape(ins, base | {"value"}, where)
                v = ins["value"]
                if typ == "i64":
                    if type(v) is not int or not -(1 << 63) <= v < (1 << 63):
                        fail(where, "i64 constant must be a signed 64-bit integer")
                elif typ == "i1":
                    if type(v) is not bool:
                        fail(where, "i1 constant must be a JSON boolean")
                else:
                    fail(where, "pointer constants are not supported")
            elif op in ARITH | BITS | CMPS:
                shape(ins, base | {"args"}, where)
                args = array(ins["args"], where)
                if len(args) != 2:
                    fail(where, "expected two operands")
                lhs = use(args[0], bid, i)
                use(args[1], bid, i, lhs)
                allowed = {"i64", "i1"} if op in BITS | {"eq", "ne"} else {"i64"}
                if lhs not in allowed:
                    fail(where, f"{op} does not support {lhs}")
                expected = "i1" if op in CMPS else lhs
                if typ != expected:
                    fail(where, f"result must have type {expected}")
            elif op == "select":
                shape(ins, base | {"cond", "yes", "no"}, where)
                use(ins["cond"], bid, i, "i1")
                use(ins["yes"], bid, i, typ)
                use(ins["no"], bid, i, typ)
            elif op == "call":
                shape(ins, base | {"function", "args"}, where)
                callee = functions.get(name(ins["function"], where))
                if callee is None:
                    fail(where, "unknown function")
                args = array(ins["args"], where)
                if len(args) != len(callee["params"]):
                    fail(where, "wrong function argument count")
                for arg, param in zip(args, callee["params"]):
                    use(arg, bid, i, param["type"])
                if typ != callee["return"]:
                    fail(where, "call result type mismatch")
                effect(callee["effects"], where)
            elif op in {"addr", "write"}:
                shape(ins, base | {"global"} | ({"fd"} if op == "write" else set()), where)
                if name(ins["global"], where) not in globals_:
                    fail(where, "unknown global")
                if typ != ("i64" if op == "write" else "ptr"):
                    fail(where, "incorrect result type")
                if op == "write":
                    use(ins["fd"], bid, i, "i64")
                    effect({"io"}, where)
            elif op == "syscall":
                shape(ins, base | {"number", "args"}, where)
                args = array(ins["args"], where)
                use(ins["number"], bid, i, "i64")
                if len(args) > 6 or typ != "i64":
                    fail(where, "syscall requires at most six arguments and i64 result")
                for arg in args:
                    if use(arg, bid, i) not in {"i64", "ptr"}:
                        fail(where, "syscall arguments must be i64 or ptr")
                effect({"io", "unsafe"}, where)
            else:
                fail(where, f"unknown operation {op}")
        t, index = b["term"], len(b["instructions"])
        if t["op"] == "ret":
            use(t["value"], bid, index, f["return"])
        else:
            if t["op"] == "branch":
                use(t["cond"], bid, index, "i1")
                edges = [t["then"], t["else"]]
            else:
                edges = [t]
            for edge in edges:
                for arg, param in zip(edge["args"], blocks[edge["target"]]["params"]):
                    use(arg, bid, index, param["type"])
