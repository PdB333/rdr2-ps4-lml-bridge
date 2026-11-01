"""Checks for the fiPackfile8 ABI decoder (no eboot, no console).

A minimal in-RAM Orbis ELF holds two hand-encoded x86-64 stubs so the
argument-register inference is exercised without any proprietary binary.
Skips entirely when capstone is not installed.
"""
from __future__ import annotations
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import inspect_rage_packfile_abi as abi  # noqa: E402
from inspect_rdr2_eboot import Image, PROGRAM  # noqa: E402

EXEC_OFF = EXEC_VA = 0x1000
SEG = 0x1000

# Hand-encoded x86-64 fragments.
PUSH_RBP = b"\x55"
SUB_RSP_18 = b"\x48\x83\xec\x18"          # sub rsp, 0x18
RET = b"\xc3"
MOV_RAX_RDI = b"\x48\x89\xf8"             # reads rdi
MOV_RAX_RSI = b"\x48\x89\xf0"             # reads rsi
MOV_RAX_RDX = b"\x48\x89\xd0"             # reads rdx
MOV_RAX_RCX = b"\x48\x89\xc8"             # reads rcx
MOV_RAX_R8 = b"\x4c\x89\xc0"              # reads r8
MOV_ESI_0 = b"\xbe\x00\x00\x00\x00"       # writes rsi (no read) first

OPEN_STUB = PUSH_RBP + SUB_RSP_18 + MOV_RAX_RDI + MOV_RAX_RSI + MOV_RAX_RDX + RET
READ_STUB = (PUSH_RBP + MOV_RAX_RDI + MOV_RAX_RSI + MOV_RAX_RDX
             + MOV_RAX_RCX + MOV_RAX_R8 + RET)
# rsi is written before any read -> not an incoming arg; breaks contiguity.
GAP_STUB = PUSH_RBP + MOV_ESI_0 + MOV_RAX_RDI + MOV_RAX_RDX + RET


def build_image() -> Image:
    raw = bytearray(0x3000)
    phoff = 0x40
    phdrs = PROGRAM.pack(1, 5, EXEC_OFF, EXEC_VA, 0, SEG, SEG, 0x4000)
    header = struct.pack("<16sHHIQQQIHHHHHH",
                         b"\x7fELF\x02\x01\x01\x09" + b"\x00" * 8, 0xFE10, 62,
                         1, 0, phoff, 0, 0, 64, PROGRAM.size, 1, 0, 0, 0)
    raw[0:len(header)] = header
    raw[phoff:phoff + len(phdrs)] = phdrs
    raw[EXEC_OFF + 0x100:EXEC_OFF + 0x100 + len(OPEN_STUB)] = OPEN_STUB
    raw[EXEC_OFF + 0x200:EXEC_OFF + 0x200 + len(READ_STUB)] = READ_STUB
    raw[EXEC_OFF + 0x300:EXEC_OFF + 0x300 + len(GAP_STUB)] = GAP_STUB
    return Image(bytes(raw))


@unittest.skipIf(abi.capstone is None, "capstone not installed")
class TestPackfileAbiDecoder(unittest.TestCase):
    def setUp(self):
        self.img = build_image()

    def test_open_three_args(self):
        s, _ = abi.analyse_one(self.img, EXEC_VA + 0x100, 160)
        self.assertEqual(s["incoming_arg_registers"], ["rdi", "rsi", "rdx"])
        self.assertEqual(s["contiguous_arg_count"], 3)
        self.assertTrue(s["standard_push_rbp_prologue"])
        self.assertEqual(s["stack_frame_bytes"], 0x18)
        self.assertTrue(s["ret_reached"])

    def test_read_five_args(self):
        s, _ = abi.analyse_one(self.img, EXEC_VA + 0x200, 160)
        self.assertEqual(s["incoming_arg_registers"],
                         ["rdi", "rsi", "rdx", "rcx", "r8"])
        self.assertEqual(s["contiguous_arg_count"], 5)

    def test_written_register_breaks_contiguity(self):
        s, _ = abi.analyse_one(self.img, EXEC_VA + 0x300, 160)
        # rsi was zeroed before any read, so it is not an incoming arg.
        self.assertNotIn("rsi", s["incoming_arg_registers"])
        self.assertIn("rdi", s["incoming_arg_registers"])
        self.assertIn("rdx", s["incoming_arg_registers"])
        self.assertEqual(s["contiguous_arg_count"], 1)  # stops at rsi


if __name__ == "__main__":
    unittest.main()
