import argparse
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from . import __version__
from .edit import apply_patch, fingerprint, save
from .environment import diagnose, example_directory
from .interpreter import ArithmeticTrap, interpret
from .verify import AILError, load, verify
from .x86 import compile_native, emit


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ail", description="Structured SSA → Linux x86-64")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="check the native compilation environment")
    doctor.add_argument("--json", action="store_true")
    commands.add_parser("examples", help="print the bundled examples directory")
    for name in ("check", "compile", "emit", "run", "interpret", "fmt", "fingerprint", "patch"):
        cmd = commands.add_parser(name)
        cmd.add_argument("source", type=Path)
        if name in {"compile", "fmt", "patch"}:
            cmd.add_argument("-o", "--output", type=Path, required=True)
        if name == "emit":
            cmd.add_argument("-o", "--output", type=Path)
        if name == "run":
            cmd.add_argument("--timeout", type=float, default=5)
        if name == "interpret":
            cmd.add_argument("--max-steps", type=int, default=1_000_000)
        if name == "patch":
            cmd.add_argument("patch_file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report = diagnose()
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                for name, check in report["checks"].items():
                    print(f"{'OK' if check['ok'] else 'MISSING'} {name}: {check['value']}")
            return 0 if report["ready"] else 2
        if args.command == "examples":
            directory = example_directory()
            if directory is None:
                raise AILError("examples are not bundled here; use the source checkout or install.sh")
            print(directory)
            return 0
        module = verify(load(args.source))
        if args.command == "check":
            print(f"OK: {len(module['functions'])} functions, {sum(len(f['blocks']) for f in module['functions'])} blocks")
        elif args.command == "compile":
            if args.output.resolve() == args.source.resolve():
                raise AILError("binary output must differ from source")
            print(compile_native(module, args.output))
        elif args.command == "emit":
            assembly = emit(module)
            if args.output:
                if args.output.resolve() == args.source.resolve():
                    raise AILError("assembly output must differ from source")
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(assembly, encoding="utf-8")
            else:
                sys.stdout.write(assembly)
        elif args.command == "run":
            if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
                raise AILError("native execution requires Linux x86-64")
            if not math.isfinite(args.timeout) or args.timeout <= 0:
                raise AILError("timeout must be finite and positive")
            with tempfile.TemporaryDirectory(prefix="ail-run-") as tmp:
                binary = compile_native(module, Path(tmp) / "program")
                code = subprocess.run([str(binary)], timeout=args.timeout).returncode
                return code if code >= 0 else 128 - code
        elif args.command == "interpret":
            result = interpret(module, args.max_steps)
            sys.stdout.buffer.write(result.stdout)
            sys.stderr.buffer.write(result.stderr)
            return result.exit_code
        elif args.command == "fmt":
            save(module, args.output)
        elif args.command == "fingerprint":
            print(fingerprint(module))
        elif args.command == "patch":
            patched = apply_patch(module, load(args.patch_file))
            save(patched, args.output)
            print(f"OK: {fingerprint(patched)}")
        return 0
    except ArithmeticTrap as exc:
        sys.stdout.buffer.write(exc.stdout)
        sys.stderr.buffer.write(exc.stderr)
        sys.stderr.buffer.flush()
        print(f"ail: {exc}", file=sys.stderr)
        return exc.exit_code
    except (AILError, OSError, subprocess.TimeoutExpired, RecursionError) as exc:
        print(f"ail: {exc}", file=sys.stderr)
        return 2
