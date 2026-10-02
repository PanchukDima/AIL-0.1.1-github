"""Bounded reference evaluator. Captures write; never executes raw syscalls."""
from dataclasses import dataclass

from .verify import AILError, ARITH, BITS, CMPS, verify


class ArithmeticTrap(AILError):
    exit_code = 125

    def __init__(self, message, stdout=b"", stderr=b""):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def signed(value):
    return (value + (1 << 63)) % (1 << 64) - (1 << 63)


@dataclass
class Result:
    value: int
    stdout: bytes
    stderr: bytes
    steps: int

    @property
    def exit_code(self):
        return self.value & 255


def interpret(module, max_steps=1_000_000):
    verify(module)
    if type(max_steps) is not int or max_steps < 1:
        raise AILError("max_steps must be positive")
    functions = {f["id"]: f for f in module["functions"]}
    globals_ = {g["id"]: g["text"].encode("utf-8") for g in module["globals"]}
    streams = {1: bytearray(), 2: bytearray()}
    steps = 0

    def tick():
        nonlocal steps
        steps += 1
        if steps > max_steps:
            raise AILError(f"interpreter exceeded step budget {max_steps}")

    def evaluate(fid, args, depth):
        if depth > 128:
            raise AILError("interpreter call depth exceeded 128")
        f = functions[fid]
        env = {p["id"]: a for p, a in zip(f["params"], args)}
        blocks = {b["id"]: b for b in f["blocks"]}
        b = f["blocks"][0]
        while True:
            for ins in b["instructions"]:
                tick()
                op = ins["op"]
                if op == "const":
                    value = int(ins["value"])
                elif op in ARITH | BITS | CMPS:
                    a, c = (env[v] for v in ins["args"])
                    if op in {"sdiv", "srem"}:
                        if c == 0 or (a == -(1 << 63) and c == -1):
                            raise ArithmeticTrap("signed division trap", bytes(streams[1]), bytes(streams[2]))
                        q = abs(a) // abs(c)
                        if (a < 0) != (c < 0):
                            q = -q
                        value = q if op == "sdiv" else a - q * c
                    elif op == "add":
                        value = signed(a + c)
                    elif op == "sub":
                        value = signed(a - c)
                    elif op == "mul":
                        value = signed(a * c)
                    elif op in BITS:
                        value = signed({"and": lambda: a & c, "or": lambda: a | c, "xor": lambda: a ^ c}[op]())
                    else:
                        value = int({"eq": lambda: a == c, "ne": lambda: a != c,
                                     "slt": lambda: a < c, "sle": lambda: a <= c,
                                     "sgt": lambda: a > c, "sge": lambda: a >= c}[op]())
                elif op == "select":
                    value = env[ins["yes"]] if env[ins["cond"]] else env[ins["no"]]
                elif op == "call":
                    value = evaluate(ins["function"], [env[a] for a in ins["args"]], depth + 1)
                elif op == "addr":
                    value = ("global", ins["global"])
                elif op == "write":
                    fd = env[ins["fd"]]
                    if fd in streams:
                        data = globals_[ins["global"]]
                        streams[fd].extend(data)
                        value = len(data)
                    else:
                        value = -9  # EBADF in the isolated reference environment.
                elif op == "syscall":
                    raise AILError("reference interpreter does not execute raw syscalls")
                env[ins["id"]] = value
            tick()
            t = b["term"]
            if t["op"] == "ret":
                return env[t["value"]]
            e = t if t["op"] == "jump" else t["then"] if env[t["cond"]] else t["else"]
            next_block = blocks[e["target"]]
            # Parallel assignment is required, including on self-loop edges.
            values = [env[a] for a in e["args"]]
            for p, value in zip(next_block["params"], values):
                env[p["id"]] = value
            b = next_block

    value = evaluate(module["entry"], [], 0)
    return Result(value, bytes(streams[1]), bytes(streams[2]), steps)
