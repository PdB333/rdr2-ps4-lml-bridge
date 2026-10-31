"""Synthetic-only wire tests for read-only RDR2 PS4 1.00 VM maps."""
from __future__ import annotations
import io
import json
import socket
import struct
import sys
import unittest
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import ps5debug_ng_rdr2_maps as maps  # noqa: E402

TEST_IP="192.168.1.181"
PID=120
GAME={
    "running_rdr2_1_00_metadata_match":True,
    "firmware":"13.40",
    "foreground_process":{
        "pid":PID,"title_id":"CUSA08519",
        "game_version_metadata":"01.00"
    },
}


def entry(name,first,last,offset=0,prot=5):
    return (name.encode("ascii").ljust(32,b"\0")+
            struct.pack("<QQQH",first,last,offset,prot))


def response(records=None,*,count=None,status=0x80000000):
    records=records if records is not None else [
        entry("eboot.bin",0x100000000,0x100100000,0,5),
        entry("eboot.bin",0x100100000,0x100200000,0x100000,1),
        entry("libSceKernel.sprx",0x200000000,0x200010000,0,5),
    ]
    n=len(records) if count is None else count
    return struct.pack("<II",status,n)+b"".join(records)


class FakeMapSocket:
    def __init__(self,wire):
        self.buf=bytearray(wire)
        self.requests=[]
        self.closed=False

    def __enter__(self):return self
    def __exit__(self,*unused):self.closed=True
    def settimeout(self,value):pass
    def sendall(self,data):self.requests.append(bytes(data))
    def recv(self,n):
        length=min(n,3,len(self.buf))
        value=bytes(self.buf[:length]);del self.buf[:length]
        return value


class TestVmMapReadOnly(unittest.TestCase):
    def test_01_valid_game_maps_read_only(self):
        fake=FakeMapSocket(response())
        with patch.object(maps,"identify",return_value=GAME) as ident, \
             patch.object(maps.socket,"create_connection",return_value=fake):
            data=maps.inspect_maps(TEST_IP)
        ident.assert_called_once_with(TEST_IP,tailscale=False,
                                      expected_fw=1340,timeout=8.0)
        self.assertEqual(data["pid"],PID)
        self.assertEqual(data["game_title_id"],"CUSA08519")
        self.assertEqual(data["game_version_metadata"],"01.00")
        self.assertEqual(data["map_metadata"]["map_count_reported"],3)
        self.assertEqual(data["map_metadata"]["executable_region_count"],2)
        self.assertEqual(data["map_metadata"]["readable_region_count"],3)
        self.assertEqual(data["map_metadata"]["candidate_image_bases_unverified"],
                         ["0x0000000100000000"])
        self.assertFalse(data["map_metadata"]["image_base_verified"])
        self.assertFalse(data["game_eboot_fingerprint_verified"])
        self.assertFalse(data["hook_installed"])
        self.assertEqual(fake.requests,[
            struct.pack("<III",0xFFAABBCC,0xBDAA0004,4)+struct.pack("<I",PID)
        ])
        self.assertTrue(fake.closed)
        self.assertNotIn("libSceKernel",str(data["map_metadata"]["named_game_region_matches"]))

    def test_02_wrong_game_version_refused_before_map_connection(self):
        false={**GAME,"running_rdr2_1_00_metadata_match":False}
        with patch.object(maps,"identify",return_value=false), \
             patch.object(maps.socket,"create_connection") as create:
            with self.assertRaisesRegex(ValueError,"non confirme"):
                maps.inspect_maps(TEST_IP)
            create.assert_not_called()

    def test_03_wrong_status_refused(self):
        fake=FakeMapSocket(response(status=0xF0000001))
        with patch.object(maps,"identify",return_value=GAME), \
             patch.object(maps.socket,"create_connection",return_value=fake):
            with self.assertRaisesRegex(ValueError,"status"):
                maps.inspect_maps(TEST_IP)

    def test_04_absurd_map_count_refused(self):
        fake=FakeMapSocket(response([],count=65535))
        with patch.object(maps,"identify",return_value=GAME), \
             patch.object(maps.socket,"create_connection",return_value=fake):
            with self.assertRaisesRegex(ValueError,"Trop de regions"):
                maps.inspect_maps(TEST_IP)

    def test_05_truncated_map_response_refused(self):
        fake=FakeMapSocket(response()[:12])
        with patch.object(maps,"identify",return_value=GAME), \
             patch.object(maps.socket,"create_connection",return_value=fake):
            with self.assertRaises(ConnectionError):
                maps.inspect_maps(TEST_IP)

    def test_06_invalid_pids_prevent_send(self):
        fake=FakeMapSocket(b"")
        for pid in (0,-1,0x80000000,1.1,None):
            with self.subTest(pid=pid),self.assertRaises(ValueError):
                maps.request_maps(fake,pid)
        self.assertEqual(fake.requests,[])

    def test_07_tailscale_route_guard(self):
        fake=FakeMapSocket(response())
        with patch.object(maps,"identify",return_value=GAME), \
             patch.object(maps,"verify_tailscale_route") as route, \
             patch.object(maps.socket,"create_connection",return_value=fake):
            data=maps.inspect_maps("100.111.222.133",tailscale=True)
        route.assert_called_once_with("100.111.222.133")
        self.assertEqual(data["pid"],PID)
        with patch.object(maps.socket,"create_connection") as create:
            with self.assertRaises(ValueError):
                maps.inspect_maps("1.2.3.4",tailscale=True)
            create.assert_not_called()

    def test_08_repeated_unknown_game_maps_are_bounded(self):
        records=[entry("eboot.bin",0x100000000+i*4096,0x100001000+i*4096,i*4096)
                 for i in range(70)]
        fake=FakeMapSocket(response(records))
        data=maps.read_map_summary(fake)
        self.assertEqual(data["map_count_reported"],70)
        self.assertEqual(len(data["named_game_region_matches"]),16)
        self.assertLessEqual(len(data["candidate_image_bases_unverified"]),12)
        self.assertLessEqual(len(data["executable_region_samples"]),5)

    def test_09_invalid_empty_mapping_ignored(self):
        fake=FakeMapSocket(response([
            entry("eboot.bin",10,10,0,0),
            entry("sample",40,30,0,0)
        ]))
        out=maps.read_map_summary(fake)
        self.assertEqual(out["map_count_reported"],2)
        self.assertEqual(out["readable_region_count"],0)
        self.assertEqual(out["named_game_region_matches"],[])

    def test_10_cli_fail_closed_on_game_mismatch(self):
        out=io.StringIO()
        err=io.StringIO()
        with patch.object(maps,"inspect_maps",side_effect=ValueError("not game")), \
             redirect_stdout(out),redirect_stderr(err):
            code=maps.main(["--ip",TEST_IP])
        self.assertEqual(code,2)
        self.assertIn("not game",err.getvalue())
        self.assertEqual(out.getvalue(),"")


if __name__=="__main__":
    unittest.main()
