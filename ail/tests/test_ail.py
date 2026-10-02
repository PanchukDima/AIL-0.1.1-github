import copy
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from ail.cli import main as cli
from ail.edit import apply_patch, fingerprint, save
from ail.interpreter import ArithmeticTrap, interpret, signed
from ail.verify import AILError, load, verify
from ail.x86 import compile_native

ROOT = Path(__file__).resolve().parents[1]


def const(id_, value, type_="i64"):
    return {"id": id_, "op": "const", "type": type_, "value": value}


def block(id_, instructions, term, params=None):
    return {"id": id_, "params": params or [], "instructions": instructions, "term": term}


def function(id_, blocks, params=None, return_="i64", effects=None):
    return {"id": id_, "params": params or [], "return": return_, "effects": effects or [], "blocks": blocks}


def module(instructions=None, result="answer"):
    return {"version": 1, "entry": "main", "globals": [], "functions": [
        function("main", [block("entry", instructions or [const("answer", 42)], {"op": "ret", "value": result})])
    ]}


class NativeTests(unittest.TestCase):
    def compare(self, m, expected=None):
        ref = interpret(m)
        if expected is not None:
            self.assertEqual(ref.value, expected)
        with tempfile.TemporaryDirectory() as tmp:
            path = compile_native(m, Path(tmp) / "app")
            native = subprocess.run([str(path)], capture_output=True, timeout=3)
        self.assertEqual(native.returncode, ref.exit_code)
        self.assertEqual(native.stdout, ref.stdout)
        self.assertEqual(native.stderr, ref.stderr)
        return ref

    def test_examples(self):
        expected = {"hello": 0, "arithmetic": 42, "factorial": 120,
                    "fibonacci": 55, "swap": 21, "recursion": 120, "six_args": 21}
        for name, value in expected.items():
            with self.subTest(example=name):
                self.compare(load(ROOT / "examples" / f"{name}.ail.json"), value)

    def test_arithmetic_differential(self):
        rng = random.Random(8172)
        pairs = [(0, 1), (-7, 3), (7, -3), (-(1 << 63), 1), ((1 << 63) - 1, 2)]
        pairs += [(rng.randrange(-(1 << 63), 1 << 63), rng.randrange(-(1 << 63), 1 << 63) or 1) for _ in range(20)]
        for op in ("add", "sub", "mul", "sdiv", "srem", "and", "or", "xor", "eq", "ne", "slt", "sle", "sgt", "sge"):
            for a, b in pairs:
                q = abs(a) // abs(b) * (-1 if (a < 0) != (b < 0) else 1)
                expected = {"add": signed(a + b), "sub": signed(a - b), "mul": signed(a * b),
                            "sdiv": q, "srem": a - q * b, "and": signed(a & b), "or": signed(a | b),
                            "xor": signed(a ^ b), "eq": a == b, "ne": a != b, "slt": a < b,
                            "sle": a <= b, "sgt": a > b, "sge": a >= b}[op]
                typ = "i1" if op in {"eq", "ne", "slt", "sle", "sgt", "sge"} else "i64"
                # Compare all 64 bits INSIDE the native executable, not only exit's low byte.
                m = module([const("a", a), const("b", b),
                            {"id": "actual", "op": op, "type": typ, "args": ["a", "b"]},
                            const("expected", expected, typ),
                            {"id": "match", "op": "eq", "type": "i1", "args": ["actual", "expected"]},
                            const("ok", 0), const("bad", 71),
                            {"id": "answer", "op": "select", "type": "i64", "cond": "match", "yes": "ok", "no": "bad"}])
                with self.subTest(op=op, a=a, b=b):
                    self.compare(m, 0)

    def test_division_traps(self):
        for op in ("sdiv", "srem"):
            for a, b in [(17, 0), (-(1 << 63), -1)]:
                m = module([const("a", a), const("b", b), {"id": "answer", "op": op, "type": "i64", "args": ["a", "b"]}])
                with self.subTest(op=op, a=a, b=b):
                    with self.assertRaises(ArithmeticTrap):
                        interpret(m)
                    with tempfile.TemporaryDirectory() as tmp:
                        path = compile_native(m, Path(tmp) / "app")
                        self.assertEqual(subprocess.run([str(path)], timeout=3).returncode, 125)

    def test_utf8_empty_and_stderr(self):
        m = module([const("fd", 2), {"id": "n", "op": "write", "type": "i64", "global": "msg", "fd": "fd"}, const("answer", 0)])
        m["functions"][0]["effects"] = ["io"]
        for text in ("Привет, мир!\n", "", "\x00\"\\\n"):
            m["globals"] = [{"id": "msg", "text": text}]
            with self.subTest(text=text):
                self.assertEqual(self.compare(m).stderr, text.encode())

    def test_boolean_operations(self):
        for op in ("and", "or", "xor"):
            for a in (True, False):
                for b in (True, False):
                    expected = {"and": a & b, "or": a | b, "xor": a ^ b}[op]
                    m = module([const("a", a, "i1"), const("b", b, "i1"),
                                {"id": "bit", "op": op, "type": "i1", "args": ["a", "b"]},
                                const("one", 1), const("zero", 0),
                                {"id": "answer", "op": "select", "type": "i64", "cond": "bit", "yes": "one", "no": "zero"}])
                    self.compare(m, int(expected))

    def test_output_before_trap(self):
        m = module([const("fd", 1), {"id": "n", "op": "write", "type": "i64", "global": "msg", "fd": "fd"},
                    const("zero", 0), {"id": "answer", "op": "sdiv", "type": "i64", "args": ["fd", "zero"]}])
        m["globals"] = [{"id": "msg", "text": "before trap\n"}]
        m["functions"][0]["effects"] = ["io"]
        with self.assertRaises(ArithmeticTrap) as caught:
            interpret(m)
        self.assertEqual(caught.exception.stdout, b"before trap\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = compile_native(m, Path(tmp) / "app")
            native = subprocess.run([str(path)], capture_output=True, timeout=3)
            self.assertEqual((native.returncode, native.stdout), (125, caught.exception.stdout))

    def test_raw_syscall_write(self):
        m = load(ROOT / "examples" / "syscall.ail.json")
        with self.assertRaisesRegex(AILError, "raw syscalls"):
            interpret(m)
        with tempfile.TemporaryDirectory() as tmp:
            path = compile_native(m, Path(tmp) / "app")
            result = subprocess.run([str(path)], capture_output=True, timeout=3)
            self.assertEqual((result.returncode, result.stdout), (0, b"Raw syscall\n"))

    def test_internal_label_collisions(self):
        m = module([{ "id": "answer", "op": "call", "type": "i64", "function": "a_b", "args": []}])
        m["functions"] += [function("a_b", [block("c", [const("v", 6)], {"op": "ret", "value": "v"})]),
                            function("a", [block("b_c", [const("v", 7)], {"op": "ret", "value": "v"})])]
        self.compare(m, 6)

    def test_elf_is_static_and_stack_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = compile_native(module(), Path(tmp) / "app")
            headers = subprocess.check_output(["readelf", "-lW", str(path)], text=True)
            self.assertNotIn("INTERP", headers)
            stack = next(line for line in headers.splitlines() if "GNU_STACK" in line)
            self.assertIn(" RW ", stack)
            self.assertNotIn("RWE", stack)


class VerifierTests(unittest.TestCase):
    def reject(self, m, message):
        with self.assertRaisesRegex(AILError, message):
            verify(m)

    def test_unknown_fields(self):
        m = module()
        m["oops"] = 3
        self.reject(m, "unknown fields")

    def test_duplicate_ssa(self):
        self.reject(module([const("answer", 1), const("answer", 2)]), "duplicate SSA")

    def test_forward_reference(self):
        self.reject(module([{ "id": "answer", "op": "add", "type": "i64", "args": ["x", "x"]}, const("x", 2)]), "before definition")

    def test_self_reference(self):
        self.reject(module([{"id": "answer", "op": "add", "type": "i64", "args": ["answer", "answer"]}]), "before definition")

    def test_undefined(self):
        self.reject(module(result="missing"), "undefined value")

    def test_bad_const(self):
        for value in (True, 1 << 63, -(1 << 63) - 1, 1.0, "5"):
            with self.subTest(value=value):
                self.reject(module([const("answer", value)]), "signed 64-bit")

    def test_boolean_const(self):
        self.reject(module([const("b", 1, "i1"), const("answer", 0)]), "JSON boolean")

    def test_invalid_type(self):
        self.reject(module([const("answer", 1, "float")]), "expected type")

    def test_bad_identifier(self):
        self.reject(module([const("answer; .global bad", 1)]), "identifier")

    def test_type_mismatch(self):
        self.reject(module([const("x", True, "i1"), const("y", 1), {"id": "answer", "op": "add", "type": "i64", "args": ["x", "y"]}]), "expected i1")

    def test_undeclared_effect(self):
        m = load(ROOT / "examples" / "hello.ail.json")
        m["functions"][0]["effects"] = []
        self.reject(m, "requires declared effects")

    def test_transitive_call_effect(self):
        m = load(ROOT / "examples" / "hello.ail.json")
        m["functions"][0]["id"] = "printer"
        m["functions"].insert(0, function("main", [block("entry", [{"id": "answer", "op": "call", "type": "i64", "function": "printer", "args": []}], {"op": "ret", "value": "answer"})]))
        self.reject(m, "requires declared effects")

    def test_bad_edge_arguments(self):
        m = load(ROOT / "examples" / "factorial.ail.json")
        m["functions"][0]["blocks"][0]["term"]["args"] = []
        self.reject(m, "wrong argument count")

    def test_bad_edge_type(self):
        m = load(ROOT / "examples" / "factorial.ail.json")
        m["functions"][0]["blocks"][0]["instructions"].insert(0, const("boolean", True, "i1"))
        m["functions"][0]["blocks"][0]["term"]["args"][0] = "boolean"
        self.reject(m, "expected i64")

    def test_unknown_target(self):
        m = load(ROOT / "examples" / "factorial.ail.json")
        m["functions"][0]["blocks"][0]["term"]["target"] = "absent"
        self.reject(m, "unknown target")

    def test_entry_backedge(self):
        m = module()
        m["functions"][0]["blocks"][0]["term"] = {"op": "jump", "target": "entry", "args": []}
        self.reject(m, "entry block")

    def test_unreachable_block(self):
        m = module()
        m["functions"][0]["blocks"].append(block("dead", [const("deadvalue", 1)], {"op": "ret", "value": "deadvalue"}))
        self.reject(m, "unreachable")

    def test_nondominating_use(self):
        m = module()
        m["functions"][0]["blocks"] = [
            block("entry", [const("yes", True, "i1"), const("zero", 0)], {"op": "branch", "cond": "yes", "then": {"target": "left", "args": []}, "else": {"target": "right", "args": []}}),
            block("left", [const("local", 3)], {"op": "jump", "target": "merge", "args": []}),
            block("right", [], {"op": "jump", "target": "merge", "args": []}),
            block("merge", [], {"op": "ret", "value": "local"})]
        self.reject(m, "does not dominate")

    def test_invalid_entry_signature(self):
        m = module()
        m["functions"][0]["params"] = [{"id": "p", "type": "i64"}]
        self.reject(m, "zero-argument")

    def test_unknown_op(self):
        m = module()
        m["functions"][0]["blocks"][0]["instructions"][0]["op"] = "magical"
        self.reject(m, "unknown operation")

    def test_invalid_structures(self):
        for m in (None, [], {"version": 1}, module([{"id": "answer", "op": [], "type": "i64"}])):
            with self.subTest(m=m):
                with self.assertRaises(AILError):
                    verify(m)

    def test_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"version":1,"version":1}')
            with self.assertRaisesRegex(AILError, "duplicate key"):
                load(path)

    def test_surrogate_global(self):
        m = module()
        m["globals"] = [{"id": "bad", "text": "\ud800"}]
        self.reject(m, "UTF-8")


class EditingAndLimitsTests(unittest.TestCase):
    def patch(self, m, value=9):
        return {"expected_sha256": fingerprint(m), "edits": [
            {"op": "replace_instruction", "function": "main", "block": "entry", "id": "answer", "value": const("answer", value)}]}

    def test_valid_edit_does_not_mutate_original(self):
        m = module()
        changed = apply_patch(m, self.patch(m))
        self.assertEqual(interpret(m).value, 42)
        self.assertEqual(interpret(changed).value, 9)

    def test_stale_edit(self):
        m = module()
        patch = self.patch(m)
        patch["expected_sha256"] = "0" * 64
        with self.assertRaisesRegex(AILError, "stale"):
            apply_patch(m, patch)

    def test_invalid_edit_rollback(self):
        m = module()
        original = copy.deepcopy(m)
        patch = self.patch(m)
        patch["edits"][0]["value"] = {"id": "answer", "op": "add", "type": "i64", "args": ["missing", "missing"]}
        with self.assertRaises(AILError):
            apply_patch(m, patch)
        self.assertEqual(m, original)

    def test_replace_function(self):
        m = module()
        patch = {"expected_sha256": fingerprint(m), "edits": [
            {"op": "replace_function", "id": "main", "value": module([const("answer", 10)])["functions"][0]}]}
        self.assertEqual(interpret(apply_patch(m, patch)).value, 10)

    def test_canonical_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.json"
            save(module(), path)
            self.assertEqual(load(path), module())

    def test_step_budget(self):
        m = module()
        m["functions"][0]["blocks"][0]["term"] = {"op": "jump", "target": "loop", "args": []}
        m["functions"][0]["blocks"].append(block("loop", [], {"op": "jump", "target": "loop", "args": []}))
        with self.assertRaisesRegex(AILError, "step budget"):
            interpret(m, 20)

    def test_call_depth_budget(self):
        m = module([{"id": "answer", "op": "call", "type": "i64", "function": "main", "args": []}])
        with self.assertRaisesRegex(AILError, "call depth"):
            interpret(m)

    def test_failed_build_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app"
            path.write_bytes(b"previous")
            bad = module(result="undefined")
            with self.assertRaises(AILError):
                compile_native(bad, path)
            self.assertEqual(path.read_bytes(), b"previous")

    def test_cli_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.json"
            save(module(), path)
            previous = path.read_bytes()
            self.assertEqual(cli(["compile", str(path), "-o", str(path)]), 2)
            self.assertEqual(path.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
