"""Unoptimized native backend: stack slots, SysV calls, GNU Intel assembly."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .verify import AILError, ARITH, BITS, CMPS, verify

CALL_REGS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
SYSCALL_REGS = ["rdi", "rsi", "rdx", "r10", "r8", "r9"]


def emit(module):
    verify(module)
    out = [".intel_syntax noprefix", ".section .rodata"]
    globals_ = {g["id"]: g["text"].encode("utf-8") for g in module["globals"]}
    for gid, data in globals_.items():
        out.append(f".L_global_{gid}:")
        if not data:
            out.append("  .byte 0")
        for i in range(0, len(data), 32):
            out.append("  .byte " + ", ".join(str(v) for v in data[i:i + 32]))
    out += [".section .text", ".global _start", ".type _start, @function",
            "_start:", "  and rsp, -16", f"  call ail_fn_{module['entry']}",
            "  mov rdi, rax", "  mov eax, 60", "  syscall", "  ud2",
            ".size _start, .-_start",
            ".L_ail_trap:", "  mov edi, 125", "  mov eax, 60", "  syscall", "  ud2"]
    for function_index, f in enumerate(module["functions"]):
        values = [p["id"] for p in f["params"]]
        for b in f["blocks"]:
            values.extend(p["id"] for p in b["params"])
            values.extend(ins["id"] for ins in b["instructions"])
        slots = {v: (i + 1) * 8 for i, v in enumerate(values)}
        max_edge_args = max(len(b["params"]) for b in f["blocks"])
        scratch = [(len(values) + i + 1) * 8 for i in range(max_edge_args)]
        frame = ((len(values) + max_edge_args) * 8 + 15) // 16 * 16
        blocks = {b["id"]: b for b in f["blocks"]}
        fid = f["id"]

        def load(value, reg="rax"):
            out.append(f"  mov {reg}, QWORD PTR [rbp - {slots[value]}]")

        def save(value, reg="rax"):
            out.append(f"  mov QWORD PTR [rbp - {slots[value]}], {reg}")

        def label(bid):
            return f".L_f{function_index}_block_{bid}"

        def edge(e):
            # Snapshot ALL edge arguments before overwriting any destination.
            for value, off in zip(e["args"], scratch):
                load(value)
                out.append(f"  mov QWORD PTR [rbp - {off}], rax")
            for p, off in zip(blocks[e["target"]]["params"], scratch):
                out.append(f"  mov rax, QWORD PTR [rbp - {off}]")
                save(p["id"])
            out.append(f"  jmp {label(e['target'])}")

        out += [f".type ail_fn_{fid}, @function", f"ail_fn_{fid}:",
                "  push rbp", "  mov rbp, rsp", f"  sub rsp, {frame}"]
        for p, reg in zip(f["params"], CALL_REGS):
            save(p["id"], reg)
        for b in f["blocks"]:
            bid = b["id"]
            out.append(label(bid) + ":")
            for ins in b["instructions"]:
                op, dst = ins["op"], ins["id"]
                out.append(f"  # {dst} = {op}")
                if op == "const":
                    out.append(f"  movabs rax, {int(ins['value'])}")
                elif op in ARITH | BITS | CMPS:
                    load(ins["args"][0])
                    load(ins["args"][1], "rcx")
                    if op in {"sdiv", "srem"}:
                        out += ["  test rcx, rcx", "  jz .L_ail_trap",
                                "  movabs rdx, -9223372036854775808", "  cmp rax, rdx"]
                        ok = f".L_f{function_index}_div_ok_{dst}"
                        out += [f"  jne {ok}", "  cmp rcx, -1", "  je .L_ail_trap", ok + ":",
                                "  cqo", "  idiv rcx"]
                        if op == "srem":
                            out.append("  mov rax, rdx")
                    elif op in CMPS:
                        cc = {"eq": "e", "ne": "ne", "slt": "l", "sle": "le", "sgt": "g", "sge": "ge"}[op]
                        out += ["  cmp rax, rcx", f"  set{cc} al", "  movzx eax, al"]
                    else:
                        opcode = "imul" if op == "mul" else op
                        out.append(f"  {opcode} rax, rcx")
                elif op == "select":
                    load(ins["no"])
                    load(ins["yes"], "rdx")
                    load(ins["cond"], "rcx")
                    out += ["  test rcx, rcx", "  cmovne rax, rdx"]
                elif op == "call":
                    for arg, reg in zip(ins["args"], CALL_REGS):
                        load(arg, reg)
                    out.append(f"  call ail_fn_{ins['function']}")
                elif op == "addr":
                    out.append(f"  lea rax, [rip + .L_global_{ins['global']}]")
                elif op == "write":
                    load(ins["fd"], "rdi")
                    out += [f"  lea rsi, [rip + .L_global_{ins['global']}]",
                            f"  mov rdx, {len(globals_[ins['global']])}", "  mov eax, 1", "  syscall"]
                elif op == "syscall":
                    for arg, reg in zip(ins["args"], SYSCALL_REGS):
                        load(arg, reg)
                    for reg in SYSCALL_REGS[len(ins["args"]):]:
                        out.append(f"  xor {reg}, {reg}")
                    load(ins["number"])
                    out.append("  syscall")
                save(dst)
            t = b["term"]
            if t["op"] == "ret":
                load(t["value"])
                out += ["  leave", "  ret"]
            elif t["op"] == "jump":
                edge(t)
            else:
                load(t["cond"])
                otherwise = f".L_f{function_index}_else_{bid}"
                out += ["  test rax, rax", f"  jz {otherwise}"]
                edge(t["then"])
                out.append(otherwise + ":")
                edge(t["else"])
        out.append(f".size ail_fn_{fid}, .-ail_fn_{fid}")
    out.append('.section .note.GNU-stack,"",@progbits')
    return "\n".join(out) + "\n"


def compile_native(module, output):
    assembly = emit(module)
    for tool in ("as", "ld"):
        if shutil.which(tool) is None:
            raise AILError(f"missing GNU {tool}; install binutils")
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ail-build-", dir=target.parent) as tmp:
        tmp = Path(tmp)
        source, obj, binary = tmp / "program.s", tmp / "program.o", tmp / "program"
        source.write_text(assembly, encoding="utf-8")
        for cmd in (["as", "--64", "-o", str(obj), str(source)],
                    ["ld", "-m", "elf_x86_64", "--build-id=none", "-z", "noexecstack",
                     "-o", str(binary), str(obj)]):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AILError(f"{cmd[0]} failed: {result.stderr.strip()}")
        binary.chmod(0o755)
        os.replace(binary, target)
    return target
