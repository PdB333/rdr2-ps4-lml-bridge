"""Synthetic read-only EBOOT 1.00 fingerprint against ps5debug-NG wire frames."""
from __future__ import annotations
import io
import re
import socket
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stderr,redirect_stdout

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import ps5debug_ng_rdr2_100_live_profile as live  # noqa: E402

IP="192.168.1.181"
PID=8123
# Layout observed live on PS5 13.40 (CUSA08519 01.00): four contiguous
# regions named "executable"; ELF p_vaddr start at 0, base = 0x00400000.
START=0x00400000
LAYOUT=((0x00400000,0x06814000,5),(0x06814000,0x06B90000,1),
        (0x06B90000,0x06E20000,3),(0x06E20000,0x08A38000,3))


def image_map(base=START,layout=LAYOUT):
    return {"main_image_regions":[{"name":"executable",
        "start":f"0x{a-START+base:016x}","end":f"0x{b-START+base:016x}",
        "offset":"0x0","prot":p} for a,b,p in layout]}


PROFILE_MAP=image_map()
REGIONS=tuple((a,b,p) for a,b,p in LAYOUT)
GAME={
    "game_title_id":"CUSA08519",
    "game_version_metadata":"01.00",
    "pid":PID,
    "firmware":"13.40",
    "map_metadata":PROFILE_MAP
}


def method_rvas() -> list[int]:
    # Exact 112 method vector from the native guard's tested fixture,
    # not a fabricated table of repetitive function addresses.
    text=(ROOT/"tests"/"test_rdr2_100_trace.cpp").read_text(encoding="utf-8")
    match=re.search(r"kMethodRvas\[112\]\s*=\s*\{([^}]+)\}",text)
    if not match:raise RuntimeError("Missing native fixture")
    values=[int(x,16) for x in re.findall(r"0x[0-9A-Fa-f]+",match.group(1))]
    if len(values)!=112:raise RuntimeError("Unexpected native table size")
    return values


def chunks(*,bias=START):
    table=b"".join(struct.pack("<Q",bias+v) for v in method_rvas())
    v={
        (live.TYPE_RVA,len(live.TYPE_NAME)):live.TYPE_NAME,
        (live.VTABLE-16,16):struct.pack("<QQ",0,bias+live.RTTI_PTR),
        (live.VTABLE,112*8):table,
        (live.VTABLE+112*8,8):b"\0"*8,
    }
    for rva,pre in live.PREFIXES.items():
        v[(rva,16)]=pre
    assert set(v)==live.READ_PLAN_SET
    return v


def response(chunks_source: dict[tuple[int,int],bytes]) -> bytes:
    return b"".join(struct.pack("<I",live.WIRE_STATUS_OK if hasattr(live,'WIRE_STATUS_OK')
                                 else 0x80000000)+chunks_source[k]
                    for k in live.READ_PLAN)


class FakeReadSocket:
    def __init__(self,wire):
        self.buf=bytearray(wire)
        self.sent=[]
    def __enter__(self):return self
    def __exit__(self,*unused):return False
    def settimeout(self,value):pass
    def sendall(self,data):self.sent.append(bytes(data))
    def recv(self,n):
        size=min(n,len(self.buf),3)
        result=bytes(self.buf[:size])
        del self.buf[:size]
        return result


class TestLiveProfileReadOnly(unittest.TestCase):
    def test_01_native_static_vtable_fnv_consistent(self):
        blob=chunks()
        status=live.validate_profile(blob,START)
        self.assertTrue(status["live_rage_packfile8_profile_matches_eboot_100"])
        self.assertEqual(status["computed_vtable_fnv64"],"8eaecb696678dad0")
        self.assertTrue(status["five_known_method_slots_match"])
        self.assertFalse(status["full_executable_sha256_verified"])
        self.assertFalse(status["game_memory_modified"])
        self.assertFalse(status["game_hook_installed"])
        self.assertFalse(status["possibly_zero_filled_read_failure"])
        self.assertGreater(status["nonzero_game_bytes_returned"],0)
        self.assertEqual(status["game_bytes_read"],1005)
        self.assertEqual(status["game_bytes_read"],sum(len(x) for x in blob.values()))

    def test_02_all_signature_mutations_fail_closed(self):
        original=chunks()
        for key in live.READ_PLAN:
            with self.subTest(key=key):
                modified=dict(original)
                arr=bytearray(modified[key])
                arr[min(8,len(arr)-1)]^=1
                modified[key]=bytes(arr)
                verdict=live.validate_profile(modified,START)
                self.assertFalse(verdict["live_rage_packfile8_profile_matches_eboot_100"])

    def test_03_relocated_image_bias_supported(self):
        bias=0x0000000200000000
        ch=chunks(bias=bias)
        status=live.validate_profile(ch,bias)
        self.assertTrue(status["live_rage_packfile8_profile_matches_eboot_100"])
        base,regions=live.select_main_image(image_map(base=bias))
        self.assertEqual(base,bias)
        self.assertEqual(regions[0][0],bias)

    def test_04_only_matching_main_executable_segment(self):
        self.assertEqual(live.select_main_image(PROFILE_MAP),(START,REGIONS))
        with self.assertRaisesRegex(ValueError,"absente ou ambigue"):
            live.select_main_image({"main_image_regions":[]})
        with self.assertRaisesRegex(ValueError,"absente ou ambigue"):
            live.select_main_image(image_map(layout=((LAYOUT[0][0],LAYOUT[0][1],1),)+LAYOUT[1:]))
        with self.assertRaisesRegex(ValueError,"non contigue"):
            live.select_main_image(image_map(layout=LAYOUT[:1]+LAYOUT[2:]))
        # Text-only map (the old 5-sample view) cannot hold the RELRO vtable.
        with self.assertRaisesRegex(ValueError,"hors de l'image"):
            live.select_main_image(image_map(layout=LAYOUT[:1]))

    def test_05_read_plan_rejects_arbitrary_address_and_length(self):
        fake=FakeReadSocket(b"")
        for rva,size in [(0x12345678,4),(live.TYPE_RVA,300),
                         (live.VTABLE,16),(live.VTABLE,902)]:
            with self.subTest(pair=(rva,size)),self.assertRaisesRegex(
                ValueError,"Lecture interdite"):
                live.read_profile_chunk(fake,PID,START,REGIONS,rva,size)
        self.assertEqual(fake.sent,[])

    def test_06_pid_and_memory_region_validated_before_request(self):
        fake=FakeReadSocket(b"")
        for pid,bias,regions in [
            (0,START,REGIONS),
            (-1,START,REGIONS),
            (PID,1<<48,REGIONS),
            (PID,0,REGIONS),
            (PID,START,((START,START+16,5),)),
            (PID,START,((START,0x08A38000,0),)),
        ]:
            with self.subTest(values=(pid,bias,regions)),self.assertRaises(ValueError):
                live.read_profile_chunk(fake,pid,bias,regions,
                                        live.TYPE_RVA,len(live.TYPE_NAME))
        self.assertEqual(fake.sent,[])

    def test_07_realistic_synthetic_wire_all_eight_reads(self):
        fake=FakeReadSocket(response(chunks()))
        with patch.object(live,"inspect_maps",return_value=GAME) as verify, \
             patch.object(live.socket,"create_connection",return_value=fake):
            report=live.check_live(IP)
        verify.assert_called_once_with(IP,tailscale=False,expected_fw=1340,
                                       timeout=8.0)
        self.assertTrue(report["profile"]["live_rage_packfile8_profile_matches_eboot_100"])
        self.assertEqual(report["image_base"],"0x400000")
        self.assertEqual(len(fake.sent),8)
        for index,(rva,length) in enumerate(live.READ_PLAN):
            self.assertEqual(fake.sent[index],struct.pack("<III",0xFFAABBCC,
                        0xBDAA0002,16)+struct.pack("<IQI",PID,START+rva,length))

    def test_08_wrong_title_or_patch_prevents_memory_access(self):
        for key,value in [("game_title_id","CUSA12345"),
                          ("game_version_metadata","01.32")]:
            game={**GAME,key:value}
            with self.subTest(field=key),\
                 patch.object(live,"inspect_maps",return_value=game), \
                 patch.object(live.socket,"create_connection") as conn:
                with self.assertRaisesRegex(ValueError,"Titre RDR2 1.00"):
                    live.check_live(IP)
                conn.assert_not_called()

    def test_09_truncated_memory_reply_refused(self):
        fake=FakeReadSocket(struct.pack("<I",0x80000000)+b"\0"*3)
        with patch.object(live,"inspect_maps",return_value=GAME), \
             patch.object(live.socket,"create_connection",return_value=fake):
            with self.assertRaises(ConnectionError):
                live.check_live(IP)

    def test_10_server_read_error_refused(self):
        fake=FakeReadSocket(struct.pack("<I",0xF0000001))
        with patch.object(live,"inspect_maps",return_value=GAME), \
             patch.object(live.socket,"create_connection",return_value=fake):
            with self.assertRaisesRegex(ValueError,"status"):
                live.check_live(IP)

    def test_11_route_guard_in_read_stage(self):
        fake=FakeReadSocket(response(chunks()))
        with patch.object(live,"inspect_maps",return_value=GAME), \
             patch.object(live,"verify_tailscale_route") as route, \
             patch.object(live.socket,"create_connection",return_value=fake):
            outcome=live.check_live("100.111.222.133",tailscale=True)
        self.assertTrue(outcome["profile"]["live_rage_packfile8_profile_matches_eboot_100"])
        route.assert_called_once_with("100.111.222.133")

    def test_12_unverified_image_base_never_inferred_from_eboot_name(self):
        maps={
            "main_image_regions":[{"name":"(NoName)eboot.bin",
                "start":"0x00000007eedf8000",
                "end":"0x00000007eedfc000","prot":0}]
        }
        with self.assertRaises(ValueError):
            live.select_main_image(maps)

    def test_13_cli_returns_nonzero_for_mismatch(self):
        game={**GAME}
        fake=FakeReadSocket(response({**chunks(),
            (live.TYPE_RVA,len(live.TYPE_NAME)):b"X"*len(live.TYPE_NAME)}))
        out,err=io.StringIO(),io.StringIO()
        with patch.object(live,"inspect_maps",return_value=game), \
             patch.object(live.socket,"create_connection",return_value=fake), \
             redirect_stdout(out),redirect_stderr(err):
            code=live.main(["--ip",IP])
        self.assertEqual(code,4)
        self.assertIn("AUCUN hook permis",err.getvalue())
        self.assertIn('"live_rage_packfile8_profile_matches_eboot_100": false',out.getvalue())

    def test_14_zero_filled_process_reads_explicitly_not_trusted(self):
        zero={key:b"\0"*len(val) for key,val in chunks().items()}
        status=live.validate_profile(zero,START)
        self.assertTrue(status["possibly_zero_filled_read_failure"])
        self.assertEqual(status["nonzero_game_bytes_returned"],0)
        self.assertFalse(status["live_rage_packfile8_profile_matches_eboot_100"])
        self.assertFalse(status["game_hook_installed"])

    def test_15_regression_absolute_rva_assumption_rejected(self):
        # Before 31 Oct 2026 the tool read base 0 + RVA. Bytes valid at
        # base+RVA must NOT validate when interpreted with bias 0.
        status=live.validate_profile(chunks(bias=START),0)
        self.assertFalse(status["live_rage_packfile8_profile_matches_eboot_100"])
        self.assertFalse(status["vtable_header_matches"])


if __name__=="__main__":
    unittest.main()
