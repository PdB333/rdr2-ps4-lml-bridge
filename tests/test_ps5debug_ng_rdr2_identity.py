"""Offline-only safety / wire tests for RDR2 PS4 game discovery via ps5debug-NG."""
from __future__ import annotations
import io
import json
import socket
import struct
import sys
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import ps5debug_ng_rdr2_identity as ident  # noqa: E402

SYNTHETIC_IP="192.168.1.181"
EXPECTED_PID=8123
CUSA="CUSA08519"   # Historical PS4 Title ID; only synthetic data in tests.


def bytestr(value: str, size: int) -> bytes:
    raw=value.encode("ascii")
    assert len(raw) < size
    return raw.ljust(size,b"\0")


def record(name: str, pid: int) -> bytes:
    return bytestr(name,32)+struct.pack("<i",pid)


def foreground(pid: int=EXPECTED_PID, *, title: str=CUSA,
               name: str="eboot.bin", version: str="1.00") -> bytes:
    return (struct.pack("<I",pid)+bytestr(title,16)+
            bytestr("SYNTHETIC_CONTENTID",64)+bytestr(name,40)+
            bytestr(version,16))


def packet(*, processes: list[tuple[str,int]]|None=None,
           foreground_data: bytes|None=None, bad_list_status: bool=False,
           count_override: int|None=None)->bytes:
    processes=processes if processes is not None else [
        ("SceShellCore", 24),("eboot.bin", EXPECTED_PID)]
    count = len(processes) if count_override is None else count_override
    status=struct.pack("<I",0xF0000001 if bad_list_status else 0x80000000)
    data=status+struct.pack("<I",count)
    if count_override is None:
        data+=b"".join(record(name,pid) for name,pid in processes)
    if any(name.lower().startswith("eboot.bin") for name,pid in processes):
        data+=struct.pack("<I",0x80000000)
        data+=foreground_data if foreground_data is not None else foreground()
    return data


class FakeGameSocket:
    def __init__(self, reply: bytes):
        self.reply=bytearray(reply)
        self.sent=[]
        self.closed=False

    def __enter__(self): return self
    def __exit__(self,*args): self.closed=True
    def settimeout(self,value): pass
    def sendall(self,value): self.sent.append(bytes(value))
    def recv(self,n):
        if not self.reply: return b""
        size=min(n,2,len(self.reply))
        b=bytes(self.reply[:size]);del self.reply[:size]
        return b


class TestReadOnlyPs5debugGameIdentity(unittest.TestCase):
    def server(self,connected=None,wire=None,*,firmware="13.40"):
        if connected is None:
            connected=FakeGameSocket(packet() if wire is None else wire)
        return connected,{
            "firmware":firmware,
            "service":"ps5debug-NG by OSR v1.3.2 [FAKE]",
            "firmware_matches_expected":firmware=="13.40",
        }

    def test_01_game_pid_title_version_found_no_write_commands(self):
        server,status=self.server()
        with patch.object(ident,"verify_service",return_value=status) as verify, \
             patch.object(ident.socket,"create_connection",return_value=server):
            data=ident.identify(SYNTHETIC_IP)
        verify.assert_called_once_with(SYNTHETIC_IP,tailscale=False,
                                        expected_fw=1340,timeout=3.0)
        self.assertTrue(data["ps4_app_version_1_00_reported"])
        self.assertTrue(data["no_memory_reads_or_game_modifications"])
        self.assertTrue(data["no_process_or_debugger_attach"])
        self.assertFalse(data["game_hook_installed"])
        self.assertTrue(data["rdr2_title_independently_verified"])
        self.assertTrue(data["running_rdr2_1_00_metadata_match"])
        self.assertFalse(data["running_eboot_fingerprint_verified"])
        self.assertEqual(data["foreground_process"]["pid"],EXPECTED_PID)
        self.assertEqual(data["foreground_process"]["title_id"],CUSA)
        self.assertEqual(data["foreground_process"]["game_version_metadata"],"1.00")
        self.assertNotIn("SYNTHETIC_CONTENTID",json.dumps(data))
        self.assertEqual(server.sent,[
            struct.pack("<III",0xFFAABBCC,0xBDAA0001,0),
            struct.pack("<III",0xFFAABBCC,0xBDDD0006,0),
        ])
        self.assertTrue(server.closed)

    def test_02_no_eboot_suppresses_second_command(self):
        server,status=self.server(wire=packet(processes=[("SceShellCore",2)]))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            data=ident.identify(SYNTHETIC_IP)
        self.assertFalse(data["ps4_app_version_1_00_reported"])
        self.assertFalse(data["foreground_process"]["process_found"])
        self.assertEqual(len(server.sent),1)

    def test_03_mismatch_firmware_refuses_all_process_requests(self):
        server,status=self.server(firmware="13.60")
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection") as conn:
            with self.assertRaisesRegex(ValueError,"Firmware non conforme"):
                ident.identify(SYNTHETIC_IP)
            conn.assert_not_called()
        self.assertEqual(len(server.sent),0)

    def test_04_wrong_status_fails_closed(self):
        server,status=self.server(wire=packet(bad_list_status=True))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            with self.assertRaisesRegex(ValueError,"status"):
                ident.identify(SYNTHETIC_IP)
        self.assertEqual(len(server.sent),1)

    def test_05_max_process_count_fails_without_payload_read(self):
        wire=packet(processes=[],count_override=5000)
        server,status=self.server(wire=wire)
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            with self.assertRaisesRegex(ValueError,"Taille inattendue"):
                ident.identify(SYNTHETIC_IP)
        self.assertEqual(len(server.sent),1)

    def test_06_truncated_process_payload_fails_closed(self):
        wire=packet()[:25]
        server,status=self.server(wire=wire)
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            with self.assertRaises(ConnectionError):
                ident.identify(SYNTHETIC_IP)

    def test_07_wrong_game_version_is_not_accepted(self):
        server,status=self.server(wire=packet(foreground_data=foreground(version="1.32")))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            data=ident.identify(SYNTHETIC_IP)
        self.assertEqual(data["foreground_process"]["game_version_metadata"],"1.32")
        self.assertFalse(data["ps4_app_version_1_00_reported"])

    def test_08_wrong_titleid_is_not_game_confirmed(self):
        server,status=self.server(wire=packet(foreground_data=foreground(title="PPSA00001")))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            data=ident.identify(SYNTHETIC_IP)
        self.assertFalse(data["ps4_app_version_1_00_reported"])
        self.assertIsNone(data["foreground_process"]["title_id"])

    def test_09_pid_must_match_eboot_proc_list(self):
        server,status=self.server(wire=packet(foreground_data=foreground(pid=42)))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            data=ident.identify(SYNTHETIC_IP)
        self.assertFalse(data["foreground_pid_in_process_list"])
        self.assertFalse(data["ps4_app_version_1_00_reported"])

    def test_10_no_foreground_game_fails_closed(self):
        server,status=self.server(wire=packet(foreground_data=foreground(pid=0,title="",name="",version="")))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            data=ident.identify(SYNTHETIC_IP)
        self.assertFalse(data["foreground_process"]["process_found"])
        self.assertFalse(data["ps4_app_version_1_00_reported"])

    def test_11_unsafe_commands_cannot_be_called(self):
        server=FakeGameSocket(b"")
        for opcode in (0xBDAA0002,0xBDAA0003,0xBDAA0004,0xBDBB0001,
                       0xBDAA0007,0xBDDD0001,0xBDCC0003):
            with self.subTest(opcode=hex(opcode)),self.assertRaisesRegex(
                ValueError,"Commande interdite"):
                ident.send_command(server,opcode)
        self.assertEqual(server.sent,[])

    def test_12_tailscale_route_and_no_public_ip(self):
        server,status=self.server()
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident,"verify_tailscale_route") as route, \
             patch.object(ident.socket,"create_connection",return_value=server):
            result=ident.identify("100.111.222.133",tailscale=True)
        route.assert_called_once_with("100.111.222.133")
        self.assertTrue(result["ps4_app_version_1_00_reported"])
        with self.assertRaises(ValueError):
            ident.identify("8.8.8.8")

    def test_13_route_failure_prevents_process_query(self):
        server,status=self.server()
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident,"verify_tailscale_route",side_effect=ValueError("route")) , \
             patch.object(ident.socket,"create_connection") as connect:
            with self.assertRaisesRegex(ValueError,"route"):
                ident.identify("100.111.222.133",tailscale=True)
        connect.assert_not_called()

    def test_14_cli_bad_metadata_returns_nonzero_no_injection(self):
        server,status=self.server(wire=packet(foreground_data=foreground(version="1.32")))
        out,err=io.StringIO(),io.StringIO()
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server), \
             redirect_stdout(out),redirect_stderr(err):
            code=ident.main(["--ip",SYNTHETIC_IP])
        self.assertEqual(code,4)
        self.assertIn('"game_version_metadata": "1.32"',out.getvalue())
        self.assertIn("non confirme",err.getvalue())

    def test_15_game_name_is_eboot_only_not_a_title_verification(self):
        # A CUSA pattern alone cannot prove the actual installed title is RDR2:
        # game identity is metadata-based, still needs game-side confirmation.
        server,status=self.server(wire=packet(foreground_data=foreground(title="CUSA12345")))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            data=ident.identify(SYNTHETIC_IP)
        self.assertTrue(data["ps4_app_version_1_00_reported"])
        self.assertFalse(data["rdr2_title_independently_verified"])
        self.assertFalse(data["running_rdr2_1_00_metadata_match"])
        self.assertEqual(data["foreground_process"]["title_id"],"CUSA12345")

    def test_16_zero_padded_sfo_game_version(self):
        self.assertTrue(ident.is_ps4_base_version("01.00"))
        self.assertTrue(ident.is_ps4_base_version("1.00"))
        self.assertTrue(ident.is_ps4_base_version("001.00"))
        for version in ("", None, "1.32", "01.32", "1.0", "01.000", "bad"):
            with self.subTest(version=version):
                self.assertFalse(ident.is_ps4_base_version(version))
        server,status=self.server(wire=packet(foreground_data=foreground(version="01.00")))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            actual=ident.identify(SYNTHETIC_IP)
        self.assertTrue(actual["running_rdr2_1_00_metadata_match"])
        self.assertFalse(actual["running_eboot_fingerprint_verified"])

    def test_17_bad_01_32_game_version_is_not_base(self):
        server,status=self.server(wire=packet(foreground_data=foreground(version="01.32")))
        with patch.object(ident,"verify_service",return_value=status), \
             patch.object(ident.socket,"create_connection",return_value=server):
            data=ident.identify(SYNTHETIC_IP)
        self.assertFalse(data["ps4_app_version_1_00_reported"])
        self.assertFalse(data["running_rdr2_1_00_metadata_match"])


if __name__=="__main__":
    unittest.main()
