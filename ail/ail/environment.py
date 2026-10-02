"""Read-only environment diagnostics and lookup of bundled source examples."""
from pathlib import Path
import platform
import shutil
import sys
import sysconfig


def example_directory():
    root = Path(__file__).resolve().parents[1]
    candidates = [root / "examples", Path(sys.prefix) / "share/ail/examples",
                  Path(sysconfig.get_path("data", scheme=sysconfig.get_preferred_scheme("user"))) / "share/ail/examples"]
    return next((p for p in candidates if (p / "hello.ail.json").is_file()), None)


def diagnose():
    checks = {
        "python": {"ok": sys.version_info >= (3, 10), "value": platform.python_version()},
        "platform": {"ok": platform.system() == "Linux", "value": platform.system()},
        "architecture": {"ok": platform.machine().lower() in {"x86_64", "amd64"}, "value": platform.machine()},
        "assembler": {"ok": shutil.which("as") is not None, "value": shutil.which("as")},
        "linker": {"ok": shutil.which("ld") is not None, "value": shutil.which("ld")},
    }
    return {"ready": all(c["ok"] for c in checks.values()), "checks": checks}
