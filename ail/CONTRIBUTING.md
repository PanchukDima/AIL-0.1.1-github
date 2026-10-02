# Contributing

Run development checks on Linux x86-64 with Python 3.10+ and GNU binutils:

```bash
python3 -m unittest discover -s tests -v
python3 tools/generate_examples.py
python3 tools/generate_schema.py
git diff --exit-code -- examples ail.schema.json
```

For a language change, update the verifier, interpreter, native backend, schema
and `docs/SPEC.md` together. Test independent expected values and native execution;
comparing only the low eight bits of an exit code is insufficient for `i64`.
Document effect changes and loop edge semantics.

Installer changes need lifecycle tests under temporary prefixes. Avoid modifying
the developer's default installation in tests. Do not commit generated binaries,
build directories, local tokens or environment files.

Keep version declarations in `ail/__init__.py` and `pyproject.toml` consistent.
Before creating a release tag, commit the intended source and run
`python3 tools/build_release.py --check-tag vVERSION` with the actual version.
The release archive builder uses tracked files and rejects a modified checkout.
