"""Dry tests for the live fiPackfile8 detour tool (no console, no writes).

check_live is mocked with a synthetic valid 1.00 report and the socket is a
fake that records the bytes the tool would send, so the write path is exercised
end to end without touching a real PS5.
"""
from __future__ import annotations
import socket
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ps5debug_ng_rdr2_100_detour as detour  # noqa: E402
import ps5debug_ng_rdr2_100_live_profile as live  # noqa: E402

IP = "192.168.1.181"
PID = 8123
BASE = 0x00400000
# Live layout: r-x text, r-- RELRO (holds the vtable), rw- data, rw- bss.
REGIONS = ((0x00400000, 0x06814000, 5), (0x06814000, 0x06B90000, 1),
           (0x06B90000, 0x06E20000, 3), (0x06E20000, 0x08A38000, 3))
TRAMP_OPEN = 0x07A00100
TRAMP_READ = 0x07A00200

OK = struct.pack("<I", detour.check_response_ok.__globals__["WIRE_STATUS_OK"])


def report(regions=REGIONS, five_ok=True, everything=True):
    return {
        "pid": PID,
        "image_base": f"0x{BASE:x}",
        "image_regions": [{"start": f"0x{a:016x}", "end": f"0x{b:016x}",
                           "prot": p} for a, b, p in regions],
        "profile": {
            "five_known_method_slots_match": five_ok,
            "live_rage_packfile8_profile_matches_eboot_100": everything,
        },
        "profile_is_read_only": True,
    }


class FakeConn:
    """Minimal socket: records sendall bytes, replies OK to every status read."""
    def __init__(self):
        self.sent = bytearray()
        self._inbox = bytearray(OK * 16)

    def settimeout(self, _):  # noqa: D401
        pass

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, size):
        take = bytes(self._inbox[:size])
        del self._inbox[:size]
        return take

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestPlan(unittest.TestCase):
    def test_slot_math(self):
        plan = detour.build_detour_plan(report(), 0, 0,
                                        require_trampolines=False)
        self.assertEqual(plan["open_slot"]["slot_addr"],
                         BASE + live.VTABLE + 2 * 8)
        self.assertEqual(plan["read_slot"]["slot_addr"],
                         BASE + live.VTABLE + 13 * 8)
        self.assertEqual(plan["open_slot"]["original_value"],
                         BASE + detour.OPEN_RVA)
        self.assertEqual(plan["read_slot"]["original_value"],
                         BASE + detour.READ_RVA)

    def test_refuses_profile_mismatch(self):
        with self.assertRaisesRegex(ValueError, "non conforme"):
            detour.build_detour_plan(report(everything=False), 0, 0,
                                     require_trampolines=False)

    def test_refuses_unconfirmed_slots(self):
        with self.assertRaisesRegex(ValueError, "non confirmes"):
            detour.build_detour_plan(report(five_ok=False), 0, 0,
                                     require_trampolines=False)

    def test_arm_requires_trampolines(self):
        with self.assertRaisesRegex(ValueError, "trampoline-open"):
            detour.build_detour_plan(report(), 0, 0, require_trampolines=True)

    def test_refuses_write_into_text(self):
        # Mark the RELRO region executable: the slot would land in r-x.
        bad = ((0x00400000, 0x06814000, 5), (0x06814000, 0x06B90000, 5),
               (0x06B90000, 0x08A38000, 3))
        with self.assertRaisesRegex(ValueError, "r-x"):
            detour.build_detour_plan(report(bad), TRAMP_OPEN, TRAMP_READ,
                                     require_trampolines=True)


class TestRun(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        with patch.object(detour.live, "check_live", return_value=report()):
            res = detour.run(IP, 0, 0)
        self.assertFalse(res["game_memory_modified"])
        self.assertEqual(res["plan"]["action"], "dry-run")

    def test_arm_sends_two_pointer_writes(self):
        conn = FakeConn()
        with patch.object(detour.live, "check_live", return_value=report()), \
             patch.object(detour.socket, "create_connection",
                          return_value=conn):
            res = detour.run(IP, TRAMP_OPEN, TRAMP_READ, arm=True)
        self.assertTrue(res["game_memory_modified"])
        # Two CMD_PROC_WRITE packets, each header(20) + 8-byte payload.
        self.assertIn(struct.pack("<Q", TRAMP_OPEN), bytes(conn.sent))
        self.assertIn(struct.pack("<Q", TRAMP_READ), bytes(conn.sent))

    def test_revert_writes_originals(self):
        conn = FakeConn()
        with patch.object(detour.live, "check_live", return_value=report()), \
             patch.object(detour.socket, "create_connection",
                          return_value=conn):
            res = detour.run(IP, 0, 0, revert=True)
        self.assertTrue(res["game_memory_modified"])
        self.assertIn(struct.pack("<Q", BASE + detour.OPEN_RVA),
                      bytes(conn.sent))
        self.assertIn(struct.pack("<Q", BASE + detour.READ_RVA),
                      bytes(conn.sent))

    def test_arm_and_revert_exclusive(self):
        with patch.object(detour.live, "check_live", return_value=report()):
            with self.assertRaisesRegex(ValueError, "exclusifs"):
                detour.run(IP, TRAMP_OPEN, TRAMP_READ, arm=True, revert=True)


if __name__ == "__main__":
    unittest.main()
