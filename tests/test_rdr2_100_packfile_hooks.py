"""Integration test for the fiPackfile8 Open/Read hook bodies (no console).

The native harness links the clean-room VFS backend and simulates the game's
original fiPackfile8::Open/Read through saved-original callbacks. Real loose
overlay bytes are supplied on disk here; no PS4 eboot is used. Skips when the
harness binary has not been built.
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "orbis_build" / "rdr2_100_packfile_hooks_harness.exe"
VIRTUAL = "update:/common/data/ai/combatbehaviour.meta"
OVERRIDE = b"MODDED_CONTENT"   # 14 bytes, matches the harness assertions
ORIGINAL = b"ORIGINAL_CONTENT"


@unittest.skipUnless(BIN.is_file(), "Build the packfile-hooks C harness first")
class TestPackfileHooksHost(unittest.TestCase):
    def test_open_read_redirect_passthrough_and_lifecycle_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = root / "payload"
            payload.mkdir()
            (payload / "override.meta").write_bytes(OVERRIDE)
            (root / "original.bin").write_bytes(ORIGINAL)
            sha = hashlib.sha256(OVERRIDE).hexdigest()
            (root / "overlay.map").write_text(
                "LML_OVERLAY_V1\n"
                "# kind/resource/payload/hash/size\n"
                f"R\t{VIRTUAL}\tpayload/override.meta\t{sha}\t{len(OVERRIDE)}\n",
                encoding="utf-8",
            )
            run = subprocess.run(
                [str(BIN), str(root)], capture_output=True, text=True,
                check=False, timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("RDR2_100_FIPACKFILE8_HOOKS_TESTS_PASSED", run.stdout)


if __name__ == "__main__":
    unittest.main()
