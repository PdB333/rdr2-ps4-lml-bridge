"""Checks for the RDR2 1.00 injection instrument (no console, no real writes)."""
from __future__ import annotations
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ps5debug_ng_rdr2_100_inject as inj  # noqa: E402

BASE = 0x00400000
PID = 120
LOADER = 0x800123456  # a plausible resolved runtime address
PATH = "/data/lml_bridge/rage_vfs.prx"
OK = struct.pack("<I", inj.WIRE_STATUS_OK)


def live_report(match=True):
    return {"pid": PID, "image_base": hex(BASE),
            "image_regions": [], "profile": {
                "live_rage_packfile8_profile_matches_eboot_100": match,
                "game_bytes_read": 1}}


class FakeConn:
    """Serves the verified ALLOC/WRITE/CALL response sequence."""
    def __init__(self, alloc_addr=0x9000000, rax=0):
        self.alloc_addr = alloc_addr
        self.rax = rax
        self.sent = []
        self.cmds = []
        self.buf = bytearray()
        self._queue_mode = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def settimeout(self, v):
        pass

    def sendall(self, data):
        self.sent.append(bytes(data))
        if len(data) >= 12 and struct.unpack_from("<I", data)[0] == inj.PACKET_MAGIC:
            cmd = struct.unpack_from("<I", data, 4)[0]
            self.cmds.append(cmd)
            if cmd == inj.CMD_PROC_ALLOC:
                self.buf += OK + struct.pack("<Q", self.alloc_addr)
            elif cmd == inj.CMD_PROC_WRITE:
                self.buf += OK  # pre-data ack; post ack queued after data
                self._queue_mode = "write"
            elif cmd == inj.CMD_PROC_CALL:
                self.buf += OK + struct.pack("<IQ", PID, self.rax)
            elif cmd == inj.CMD_PROC_FREE:
                self.buf += OK
        elif self._queue_mode == "write":
            self.buf += OK  # post-write confirmation after raw data phase
            self._queue_mode = None

    def recv(self, n):
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


class TestInjectDryRun(unittest.TestCase):
    def test_dry_run_sends_nothing_and_builds_plan(self):
        conn = FakeConn()
        with patch.object(inj.live, "check_live", return_value=live_report()), \
             patch.object(inj.socket, "create_connection",
                          return_value=conn) as create:
            out = inj.inject("192.168.1.50", PATH, LOADER, arm=False)
        create.assert_not_called()
        self.assertFalse(out["armed"])
        self.assertFalse(out["game_memory_modified"])
        self.assertEqual([s["op"] for s in out["plan"]["steps"]],
                         ["ALLOC", "WRITE", "CALL"])
        self.assertEqual(out["plan"]["loader_addr"], f"0x{LOADER:X}")

    def test_missing_loader_addr_refused(self):
        with patch.object(inj.live, "check_live", return_value=live_report()):
            with self.assertRaisesRegex(ValueError, "loader-addr"):
                inj.inject("192.168.1.50", PATH, 0, arm=False)

    def test_bad_path_refused(self):
        with patch.object(inj.live, "check_live", return_value=live_report()):
            with self.assertRaisesRegex(ValueError, "Chemin module refuse"):
                inj.inject("192.168.1.50", "relative/x.prx", LOADER, arm=False)

    def test_profile_mismatch_blocks_everything(self):
        with patch.object(inj.live, "check_live",
                          return_value=live_report(False)), \
             patch.object(inj.socket, "create_connection") as create:
            with self.assertRaisesRegex(ValueError, "injection refusee"):
                inj.inject("192.168.1.50", PATH, LOADER, arm=True)
        create.assert_not_called()


class TestInjectArmed(unittest.TestCase):
    def run_armed(self, conn):
        with patch.object(inj.live, "check_live", return_value=live_report()), \
             patch.object(inj.socket, "create_connection", return_value=conn), \
             patch.object(inj, "validate_local_ip", return_value="192.168.1.50"):
            return inj.inject("192.168.1.50", PATH, LOADER, arm=True)

    def test_armed_runs_alloc_write_call_free(self):
        conn = FakeConn(alloc_addr=0x9ABC000, rax=7)
        out = self.run_armed(conn)
        self.assertEqual(conn.cmds, [inj.CMD_PROC_ALLOC, inj.CMD_PROC_WRITE,
                                     inj.CMD_PROC_CALL, inj.CMD_PROC_FREE])
        self.assertTrue(out["game_memory_modified"])
        self.assertEqual(out["alloc_addr"], "0x9ABC000")
        self.assertEqual(out["module_handle"], 7)
        self.assertTrue(out["loaded"])
        # The written bytes are exactly the NUL-terminated path.
        self.assertIn(PATH.encode() + b"\0", conn.sent)

    def test_negative_handle_reported_not_loaded(self):
        conn = FakeConn(rax=(1 << 64) - 1)  # -1 errno as unsigned rax
        out = self.run_armed(conn)
        self.assertEqual(out["module_handle"], -1)  # interpreted signed
        self.assertFalse(out["loaded"])
        self.assertEqual(out["rax"], "0xFFFFFFFFFFFFFFFF")


if __name__ == "__main__":
    unittest.main()
