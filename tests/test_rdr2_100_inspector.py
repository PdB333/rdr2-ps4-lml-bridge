"""RDR2 1.00 EBOOT verifier: refusal and published profile integrity."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/"tools"/"verify_eboot_100.py"
HEADER=ROOT/"runtime"/"rdr2_100_pack_trace.h"
KNOWN_SHA="e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff"


class TestRdr2OneHundredInspector(unittest.TestCase):
    def test_invalid_and_unknown_eboot_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            fake=Path(folder)/"eboot.bin"
            fake.write_bytes(b"\x7fELF\x02\x01\x01\x09"+b"\0"*200)
            result=subprocess.run([sys.executable,"-B",str(TOOL),str(fake)],
                                  text=True,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,2)
            self.assertIn("Not the known RDR2 PS4 1.00 EBOOT",result.stderr)

    def test_reproducible_full_vtable_fingerprint_constant(self):
        code=TOOL.read_text(encoding="utf-8")
        header=HEADER.read_text(encoding="utf-8")
        self.assertIn(KNOWN_SHA,code)
        self.assertIn("0x8EAECB696678DAD0",code)
        self.assertIn("0x8EAECB696678DAD0",header)
        self.assertIn("SLOTS=112",code)
        self.assertIn("live_hook_installed",code)
        self.assertIn('"supports_ps4_1_32":False',code)
        self.assertTrue((ROOT/"orbis"/"EBOOT_RAGE_VFS_PROFILE.md").is_file())


if __name__=="__main__":
    unittest.main()
