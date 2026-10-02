#!/usr/bin/env python3
"""Offline user installation with an atomic launcher and managed release roots."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

PRODUCT = "ail-installer-v1"
RELEASE_ID = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{16}\Z")
ROOT_MARKER = ".ail-managed.json"
RELEASE_MARKER = ".ail-release.json"
SOURCE = Path(__file__).resolve().parents[1]


class InstallError(RuntimeError):
    pass


def atomic_text(path, text, mode=0o644):
    fd, temporary = tempfile.mkstemp(prefix=".ail-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_record(path):
    try:
        if path.is_symlink():
            raise InstallError(f"refusing symlink metadata: {path}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("product") != PRODUCT:
            raise InstallError(f"not an AIL managed installation: {path}")
        return record
    except (OSError, ValueError) as exc:
        raise InstallError(f"invalid installation metadata: {path}") from exc


def launcher_header(root):
    return '#!/usr/bin/env python3\n# Managed by AIL installer v1\n# root-json: ' + json.dumps(str(root)) + '\n'


def check_launcher(launcher, root):
    if launcher.is_symlink():
        raise InstallError(f"refusing to replace a symlink: {launcher}")
    if launcher.exists():
        if not launcher.is_file() or not launcher.read_text(encoding="utf-8", errors="replace").startswith(launcher_header(root)):
            raise InstallError(f"{launcher} exists and is not managed by this installer; choose another --prefix")


@contextmanager
def installation_lock(root):
    lock = root / ".install.lock"
    if lock.is_symlink():
        raise InstallError("refusing symlink install lock")
    import fcntl  # Linux-only installer; no external Python dependency.
    with lock.open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


def source_files():
    required = ["ail/__init__.py", "ail/cli.py", "examples/hello.ail.json", "ail.schema.json", "LICENSE", "README.md"]
    if any(not (SOURCE / p).is_file() for p in required):
        raise InstallError("installer must run from a complete AIL source tree")
    files = []
    for directory in ("ail", "examples", "docs", "scripts"):
        for p in (SOURCE / directory).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                if p.is_symlink():
                    raise InstallError(f"source file must not be a symlink: {p}")
                files.append(p)
    files += [SOURCE / p for p in ("ail.schema.json", "README.md", "LICENSE", "install.sh", "uninstall.sh")]
    return sorted(set(files))


def release_identity(files):
    text = (SOURCE / "ail/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"$', text, re.MULTILINE)
    if match is None:
        raise InstallError("source has no supported version declaration")
    version = match.group(1)
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(SOURCE).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big") + relative)
        digest.update(len(data).to_bytes(8, "big") + data)
    identity = f"{version}-{digest.hexdigest()[:16]}"
    if not RELEASE_ID.fullmatch(identity):
        raise InstallError("invalid source version")
    return version, identity


def smoke(release):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # -I omits the working directory; load exactly this candidate release.
    script = 'import sys;sys.path.insert(0,sys.argv[1]);from ail.cli import main;raise SystemExit(main(sys.argv[2:]))'
    command = [sys.executable, "-I", "-B", "-c", script, str(release), "run", str(release / "examples/hello.ail.json"), "--timeout", "5"]
    result = subprocess.run(command, cwd=release, env=env, capture_output=True, timeout=15)
    if (result.returncode, result.stdout, result.stderr) != (0, b"Hello from AIL!\n", b""):
        raise InstallError("candidate installation failed the native Hello World check: " + result.stderr.decode(errors="replace"))


def validate_release(path, root, identity):
    if not RELEASE_ID.fullmatch(identity) or path.is_symlink() or path.resolve().parent != (root / "versions").resolve():
        raise InstallError(f"invalid managed release path: {path}")
    record = read_record(path / RELEASE_MARKER)
    if record.get("identity") != identity:
        raise InstallError(f"release identity mismatch: {path}")
    return record


def install(prefix):
    root, launcher = prefix / "share/ail", prefix / "bin/ail"
    check_launcher(launcher, root)
    if root.is_symlink():
        raise InstallError("installation root must not be a symlink")
    if root.exists() and not (root / ROOT_MARKER).is_file():
        raise InstallError(f"{root} already exists without AIL ownership metadata")
    files = source_files()
    version, identity = release_identity(files)
    root.mkdir(parents=True, exist_ok=True)
    with installation_lock(root):
        check_launcher(launcher, root)
        state = read_record(root / ROOT_MARKER) if (root / ROOT_MARKER).exists() else {"product": PRODUCT, "releases": []}
        if not isinstance(state.get("releases"), list):
            raise InstallError("invalid managed release list")
        if not (root / ROOT_MARKER).exists():
            atomic_text(root / ROOT_MARKER, json.dumps(state, indent=2) + "\n")
        versions = root / "versions"
        if versions.is_symlink():
            raise InstallError("versions directory must not be a symlink")
        versions.mkdir(exist_ok=True)
        target = versions / identity
        if target.exists() or target.is_symlink():
            validate_release(target, root, identity)
            record = read_record(target / RELEASE_MARKER)
            for relative, digest in record["files"].items():
                file = target / relative
                if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                    raise InstallError(f"installed release was modified: {file}; uninstall before reinstalling")
            smoke(target)
        else:
            with tempfile.TemporaryDirectory(prefix=".stage-", dir=versions) as staging:
                stage = Path(staging) / identity
                stage.mkdir()
                hashes = {}
                for source in files:
                    relative = source.relative_to(SOURCE)
                    dest = stage / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, dest)
                    dest.chmod(0o755 if dest.suffix == ".sh" else 0o644)
                    hashes[relative.as_posix()] = hashlib.sha256(dest.read_bytes()).hexdigest()
                record = {"product": PRODUCT, "identity": identity, "version": version, "files": hashes}
                (stage / RELEASE_MARKER).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
                smoke(stage)
                os.replace(stage, target)
        if identity not in state["releases"]:
            state["releases"].append(identity)
        state["active"] = identity
        # Record ownership before activating the new launcher. Old launcher
        # remains usable if activation fails; a reinstall may retry activation.
        atomic_text(root / ROOT_MARKER, json.dumps(state, indent=2) + "\n")
        launcher.parent.mkdir(parents=True, exist_ok=True)
        body = launcher_header(root) + (
            "import sys\nfrom pathlib import Path\n"
            "sys.dont_write_bytecode = True\n"
            "if sys.version_info < (3, 10):\n"
            "    raise SystemExit('AIL requires Python 3.10+')\n"
            f"sys.path.insert(0, {str(target)!r})\n"
            "from ail.cli import main\nraise SystemExit(main())\n"
        )
        atomic_text(launcher, body, 0o755)
    print(f"Installed AIL {version}: {launcher}")
    print(f"Examples: {target / 'examples'}")
    print(f"For the current shell: export PATH={shlex.quote(str(launcher.parent))}:\"$PATH\"")
    print("Then run: ail doctor")


def uninstall(prefix):
    root, launcher = prefix / "share/ail", prefix / "bin/ail"
    if root.is_symlink():
        raise InstallError("installation root must not be a symlink")
    if not root.exists():
        print("AIL is not installed at this prefix")
        return
    with installation_lock(root):
        state = read_record(root / ROOT_MARKER)
        if not isinstance(state.get("releases"), list):
            raise InstallError("invalid managed release list")
        check_launcher(launcher, root)
        versions = root / "versions"
        if versions.is_symlink():
            raise InstallError("versions directory must not be a symlink")
        owned = []
        for identity in state["releases"]:
            path = versions / identity
            validate_release(path, root, identity)
            owned.append(path)
        # Validate all ownership before removing any launcher or release.
        launcher.unlink(missing_ok=True)
        for path in owned:
            shutil.rmtree(path)
        # Keep a stable lock/root to avoid concurrent lock inode replacement;
        # a tombstone marks this empty owned installation for the next install.
        atomic_text(root / ROOT_MARKER, json.dumps({"product": PRODUCT, "releases": []}) + "\n")
    print(f"Uninstalled AIL from {prefix}; project source files are unchanged")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install or remove AIL without pip or sudo")
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise InstallError("Python 3.10+ is required")
        if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
            raise InstallError("this installer supports Linux x86-64; on Windows use WSL2 x86-64")
        prefix = args.prefix.expanduser().resolve()
        if args.uninstall:
            uninstall(prefix)
        else:
            for tool in ("as", "ld"):
                if shutil.which(tool) is None:
                    raise InstallError(f"missing {tool}; install GNU binutils first")
            install(prefix)
        return 0
    except (InstallError, OSError, subprocess.TimeoutExpired, KeyError, TypeError) as exc:
        print(f"AIL installer: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
