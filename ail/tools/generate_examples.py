"""Reproduce the checked-in example graphs without a handwritten grammar."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def c(id_, value, typ="i64"):
    return {"id": id_, "op": "const", "type": typ, "value": value}


def op(id_, opcode, *args, typ="i64"):
    return {"id": id_, "op": opcode, "type": typ, "args": list(args)}


def params(*names):
    return [{"id": n, "type": "i64"} for n in names]


def b(id_, instructions, term, ps=None):
    return {"id": id_, "params": ps or [], "instructions": instructions, "term": term}


def fn(id_, blocks, ps=None, effects=None):
    return {"id": id_, "params": ps or [], "return": "i64", "effects": effects or [], "blocks": blocks}


def ret(v):
    return {"op": "ret", "value": v}


def edge(target, *args):
    return {"target": target, "args": list(args)}


def jump(target, *args):
    return {"op": "jump", **edge(target, *args)}


def branch(cond, yes, no):
    return {"op": "branch", "cond": cond, "then": yes, "else": no}


def call(id_, function, *args):
    return {"id": id_, "op": "call", "type": "i64", "function": function, "args": list(args)}


def write(id_, global_, fd):
    return {"id": id_, "op": "write", "type": "i64", "global": global_, "fd": fd}


def program(*functions, globals_=None):
    return {"version": 1, "entry": "main", "globals": globals_ or [], "functions": list(functions)}


def main():
    examples = {}
    examples["hello"] = program(fn("main", [b("entry", [c("stdout", 1), write("written", "greeting", "stdout"), c("exit_code", 0)], ret("exit_code"))], effects=["io"]),
                                globals_=[{"id": "greeting", "text": "Hello from AIL!\n"}])
    examples["arithmetic"] = program(
        fn("main", [b("entry", [c("a", 6), c("b", 7), call("answer", "multiply", "a", "b")], ret("answer"))]),
        fn("multiply", [b("entry", [op("result", "mul", "lhs", "rhs")], ret("result"))], params("lhs", "rhs")))
    examples["factorial"] = program(fn("main", [
        b("entry", [c("start", 5), c("one", 1)], jump("loop", "start", "one")),
        b("loop", [op("done", "sle", "n", "one", typ="i1")], branch("done", edge("exit", "acc"), edge("body", "n", "acc")), params("n", "acc")),
        b("body", [op("product", "mul", "old_acc", "old_n"), op("next_n", "sub", "old_n", "one")], jump("loop", "next_n", "product"), params("old_n", "old_acc")),
        b("exit", [], ret("answer"), params("answer"))]))
    examples["fibonacci"] = program(fn("main", [
        b("entry", [c("zero", 0), c("one", 1), c("count", 10)], jump("loop", "zero", "one", "count")),
        b("loop", [op("done", "eq", "n", "zero", typ="i1")], branch("done", edge("exit", "a"), edge("body", "a", "b", "n")), params("a", "b", "n")),
        b("body", [op("next", "add", "old_a", "old_b"), op("remaining", "sub", "old_n", "one")], jump("loop", "old_b", "next", "remaining"), params("old_a", "old_b", "old_n")),
        b("exit", [], ret("answer"), params("answer"))]))
    examples["swap"] = program(fn("main", [
        b("entry", [c("x", 1), c("y", 2), c("once", 1), c("zero", 0), c("ten", 10)], jump("loop", "x", "y", "once")),
        b("loop", [op("done", "eq", "n", "zero", typ="i1")], branch("done", edge("exit", "a", "b"), edge("loop", "b", "a", "zero")), params("a", "b", "n")),
        b("exit", [op("tens", "mul", "left", "ten"), op("answer", "add", "tens", "right")], ret("answer"), params("left", "right"))]))
    examples["recursion"] = program(
        fn("main", [b("entry", [c("five", 5), call("answer", "factorial", "five")], ret("answer"))]),
        fn("factorial", [
            b("entry", [c("one", 1), op("base", "sle", "n", "one", typ="i1")], branch("base", edge("stop"), edge("recurse"))),
            b("stop", [], ret("one")),
            b("recurse", [op("smaller", "sub", "n", "one"), call("subresult", "factorial", "smaller"), op("answer", "mul", "n", "subresult")], ret("answer"))], params("n")))
    examples["six_args"] = program(
        fn("main", [b("entry", [c(f"v{i}", i) for i in range(1, 7)] + [call("answer", "sum6", *(f"v{i}" for i in range(1, 7)))], ret("answer"))]),
        fn("sum6", [b("entry", [op("s1", "add", "a", "b"), op("s2", "add", "s1", "c"), op("s3", "add", "s2", "d"), op("s4", "add", "s3", "e"), op("s5", "add", "s4", "f")], ret("s5"))], params("a", "b", "c", "d", "e", "f")))
    examples["syscall"] = program(fn("main", [b("entry", [c("nr", 1), c("fd", 1), c("len", 12), {"id": "ptr", "op": "addr", "type": "ptr", "global": "message"},
                                                   {"id": "written", "op": "syscall", "type": "i64", "number": "nr", "args": ["fd", "ptr", "len"]}, c("exit_code", 0)], ret("exit_code"))], effects=["io", "unsafe"]),
                                  globals_=[{"id": "message", "text": "Raw syscall\n"}])
    (ROOT / "examples").mkdir(exist_ok=True)
    for name, m in examples.items():
        (ROOT / "examples" / f"{name}.ail.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
