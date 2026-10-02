#!/usr/bin/env python3
"""Build an installer source archive from tracked files, without uploading it."""
import argparse
import hashlib
import io
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ail.x86 import compile_native, emit
from ail.verify import load


def project_version():
    match = re.search(r'^__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"$', (ROOT / "ail/__init__.py").read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError("invalid project version")
    version = match.group(1)
    if f'version = "{version}"' not in (ROOT / "pyproject.toml").read_text():
        raise RuntimeError("pyproject and Python versions differ")
    return version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-tag")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = project_version()
    if args.check_tag:
        if args.check_tag != "v" + version:
            raise SystemExit("release tag does not match project version")
        print("OK: " + args.check_tag)
        return
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    paths = [p for p in tracked if p]
    if not paths:
        raise SystemExit("no tracked source files; run from a prepared git checkout")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT).strip():
        raise SystemExit("tracked files are modified; commit changes before building a release")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / f"ail-{version}-linux-x86_64.tar.gz"
    content = {p: (ROOT / p).read_bytes() for p in paths}
    with tempfile.TemporaryDirectory(prefix="ail-release-") as tmp:
        hello = load(ROOT / "examples/hello.ail.json")
        binary = compile_native(hello, Path(tmp) / "hello")
        result = subprocess.run([str(binary)], capture_output=True, timeout=5)
        if (result.returncode, result.stdout) != (0, b"Hello from AIL!\n"):
            raise SystemExit("prebuilt demo failed")
        content["prebuilt/hello-linux-x86_64"] = binary.read_bytes()
        content["prebuilt/hello.s"] = emit(hello).encode()
    sums = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n" for name, data in sorted(content.items()))
    content["SHA256SUMS"] = sums.encode()
    with tarfile.open(target, "w:gz") as archive:
        for name, data in sorted(content.items()):
            entry = tarfile.TarInfo(f"ail-{version}/" + name)
            entry.size = len(data)
            entry.mode = 0o755 if name.endswith(".sh") or name == "prebuilt/hello-linux-x86_64" else 0o644
            entry.mtime = 0
            archive.addfile(entry, io.BytesIO(data))
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix + ".sha256").write_text(checksum + "  " + target.name + "\n")
    print(target)


if __name__ == "__main__":
    main()
