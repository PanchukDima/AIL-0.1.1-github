# AIL — structured programs for AI code generation

[Русская документация](README.ru.md) · [AI agent guide](docs/AI_GUIDE.md) ·
[Language specification](docs/SPEC.md) · [Installation](docs/INSTALL.md)

AIL 0.1.1 is a working compiler prototype: a typed JSON SSA graph becomes a
**standalone Linux x86-64 ELF executable**. The Python compiler implements its
own x86-64 assembly generation and uses GNU `as` and `ld` for encoding and linking.
The executable does not require Python, LLVM or libc.

The experiment is to make program construction and local edits explicit and
verifiable for AI tools. Benefits over existing languages have **not** been
measured. AIL remains a small prototype rather than a general-purpose replacement.

## Install

Requirements: Linux x86-64, Python 3.10+, GNU binutils. From the source directory:

```bash
sh install.sh
export PATH="$HOME/.local/bin:$PATH"
ail doctor
AIL_EXAMPLES=$(ail examples)
ail run "$AIL_EXAMPLES/hello.ail.json" --timeout 5
```

Expected output: `Hello from AIL!`. The installer is offline, does not use pip
or sudo, and tests the candidate compiler before activating its launcher.
Choose another destination with `sh install.sh --prefix /your/path`.
Uninstall with `sh uninstall.sh` using the same prefix if customized.

## Compile without installing

```bash
python3 -m ail check examples/hello.ail.json
python3 -m ail compile examples/hello.ail.json -o build/hello
./build/hello
```

## Features

- Strict JSON graph structure, `i64`, `i1`, `ptr`, and 20 opcodes.
- Functions, six arguments, recursion, branches and loops.
- SSA dominance checking and block arguments with parallel edge transfers.
- Declared function effects, static UTF-8 output and explicit raw Linux syscalls.
- A bounded reference interpreter for differential validation.
- Verified edits by stable identifiers with a canonical graph hash precondition.
- User installer, environment diagnostics and bundled examples.

No floats, heap, mutable arrays, FFI, Windows/ARM backend, optimizer or self-hosting
are implemented. Native values use stack slots. Raw syscalls are not sandboxed.
The interpreter does not execute raw syscalls. JSON Schema checks structure;
the verifier additionally checks types and graph semantics.

## Commands

```text
ail check SOURCE
ail compile SOURCE -o BINARY
ail emit SOURCE -o ASSEMBLY
ail run SOURCE --timeout 5
ail interpret SOURCE --max-steps 1000000
ail fmt SOURCE -o OUTPUT
ail fingerprint SOURCE
ail patch SOURCE PATCH -o OUTPUT
ail doctor [--json]
ail examples
```

`run` and `interpret` return the program's exit status. For example, the arithmetic
example returns 42 and factorial returns 120; these are intentional results.
A native exit status only contains eight bits. Full `i64` validation requires
in-program assertions or the reference interpreter's full result value.

## Development and distributions

```bash
python3 -m unittest discover -s tests -v
python3 tools/build_release.py
```

The source release builder requires a clean git checkout. It creates a tar.gz
with the installer, documentation, examples, checksums and a native demo.
Python wheel/sdist builds use `python3 -m build` after installing the `build` tool.

GitHub Actions test Python 3.10, 3.12 and 3.13 on Ubuntu x86-64. A separate workflow
builds downloadable artifacts for version tags or manual runs. It does not
automatically publish a GitHub Release or a PyPI package.

Locally validated on Python 3.12.14: **53 tests**, including 350 arithmetic
comparisons and installer lifecycle tests. Other Python versions are configured
in CI and have not yet been run in GitHub Actions for this repository.

[GitHub upload instructions](docs/GITHUB.md) · [Contributing](CONTRIBUTING.md) ·
[Roadmap](docs/ROADMAP.md) · [Changelog](CHANGELOG.md)

## License

MIT. See [LICENSE](LICENSE).
