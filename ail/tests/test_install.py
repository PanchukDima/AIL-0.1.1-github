import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ail.environment import diagnose

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ail-install-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.prefix = self.work / "prefix with spaces"

    def installer(self, *options, root=ROOT, expected=0):
        result = subprocess.run(["sh", str(root / "install.sh"), "--prefix", str(self.prefix), *options],
                                cwd=self.work, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def command(self, *args, expected=0):
        result = subprocess.run([str(self.prefix / "bin/ail"), *args], cwd=self.work,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def test_install_and_native_demo_outside_checkout(self):
        self.installer()
        self.assertEqual(self.command("--version").stdout.strip(), "0.1.1")
        report = json.loads(self.command("doctor", "--json").stdout)
        self.assertTrue(report["ready"])
        examples = Path(self.command("examples").stdout.strip())
        self.assertTrue(examples.is_relative_to(self.prefix))
        self.assertEqual(self.command("run", str(examples / "hello.ail.json")).stdout, "Hello from AIL!\n")

    def test_reinstall_is_idempotent(self):
        self.installer()
        before = (self.prefix / "bin/ail").read_bytes()
        self.installer()
        self.assertEqual((self.prefix / "bin/ail").read_bytes(), before)
        versions = list((self.prefix / "share/ail/versions").iterdir())
        self.assertEqual(len(versions), 1)

    def test_upgrade_keeps_previous_release(self):
        checkout = self.work / "checkout"
        shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", "build", "dist", "__pycache__", "*.egg-info", "prebuilt"))
        self.installer(root=checkout)
        first = (self.prefix / "bin/ail").read_bytes()
        with (checkout / "README.md").open("a") as stream:
            stream.write("\nTest a different release content hash.\n")
        self.installer(root=checkout)
        self.assertNotEqual((self.prefix / "bin/ail").read_bytes(), first)
        self.assertEqual(len(list((self.prefix / "share/ail/versions").iterdir())), 2)
        self.command("--version")

    def test_source_is_not_needed_after_installation(self):
        checkout = self.work / "checkout"
        shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", "build", "dist", "__pycache__", "*.egg-info", "prebuilt"))
        self.installer(root=checkout)
        checkout.rename(self.work / "old-checkout")
        self.command("--version")
        examples = self.command("examples").stdout.strip()
        self.command("run", str(Path(examples) / "hello.ail.json"))

    def test_uninstall_and_reinstall(self):
        self.installer()
        unrelated = self.prefix / "bin/unrelated"
        unrelated.write_text("keep this")
        self.installer("--uninstall")
        self.assertFalse((self.prefix / "bin/ail").exists())
        self.assertEqual(list((self.prefix / "share/ail/versions").iterdir()), [])
        self.assertEqual(unrelated.read_text(), "keep this")
        self.installer("--uninstall")
        self.installer()
        self.command("--version")

    def test_uninstall_wrapper(self):
        self.installer()
        result = subprocess.run(["sh", str(ROOT / "uninstall.sh"), "--prefix", str(self.prefix)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.prefix / "bin/ail").exists())

    def test_foreign_executable_is_preserved(self):
        path = self.prefix / "bin/ail"
        path.parent.mkdir(parents=True)
        path.write_text("someone else's program")
        result = self.installer(expected=2)
        self.assertIn("not managed", result.stderr)
        self.assertEqual(path.read_text(), "someone else's program")

    def test_symlink_executable_is_preserved(self):
        path = self.prefix / "bin/ail"
        path.parent.mkdir(parents=True)
        external = self.work / "foreign"
        external.write_text("keep")
        path.symlink_to(external)
        self.installer(expected=2)
        self.assertTrue(path.is_symlink())
        self.assertEqual(external.read_text(), "keep")

    def test_foreign_data_directory_is_preserved(self):
        root = self.prefix / "share/ail"
        root.mkdir(parents=True)
        (root / "foreign").write_text("keep")
        self.installer(expected=2)
        self.assertEqual((root / "foreign").read_text(), "keep")

    def test_modified_installation_is_not_silently_overwritten(self):
        self.installer()
        examples = Path(self.command("examples").stdout.strip())
        target = examples.parent / "README.md"
        target.write_text("local modification")
        result = self.installer(expected=2)
        self.assertIn("modified", result.stderr)
        self.assertEqual(target.read_text(), "local modification")

    def test_uninstall_rejects_symlink_release(self):
        self.installer()
        root = self.prefix / "share/ail"
        state = json.loads((root / ".ail-managed.json").read_text())
        version = root / "versions" / state["active"]
        outside = self.work / "outside"
        version.rename(outside)
        version.symlink_to(outside, target_is_directory=True)
        self.installer("--uninstall", expected=2)
        self.assertTrue((self.prefix / "bin/ail").exists())
        self.assertTrue((outside / "README.md").exists())

    def test_doctor_reports_missing_tools(self):
        with patch("ail.environment.shutil.which", return_value=None):
            report = diagnose()
        self.assertFalse(report["ready"])
        self.assertFalse(report["checks"]["assembler"]["ok"])


if __name__ == "__main__":
    unittest.main()
