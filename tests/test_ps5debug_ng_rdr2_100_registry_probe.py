"""Synthetic read-only checks for the fiCollection registry probe."""
from __future__ import annotations
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import ps5debug_ng_rdr2_100_registry_probe as reg  # noqa: E402

BASE=0x00400000
REGIONS=((0x00400000,0x06814000,5),(0x06814000,0x06B90000,1),
         (0x06B90000,0x06E20000,3),(0x06E20000,0x08A38000,3))
PID=120
OK=0x80000000


def live_report(match=True):
    return {"pid":PID,"image_base":hex(BASE),
            "image_regions":[{"start":hex(a),"end":hex(b),"prot":p}
                             for a,b,p in REGIONS],
            "profile":{"live_rage_packfile8_profile_matches_eboot_100":match,
                       "game_bytes_read":1005}}


def fixture():
    slots=[0]*reg.SLOTS
    objects={}
    slots[0]=0x208A1AE50  # other collection type (pgRawStreamer seen live)
    objects[slots[0]]=struct.pack("<QH",BASE+0x066B2018,0)+b"\0"*6
    for i in range(1,5):
        slots[i]=0x202000000+i*0x100
        objects[slots[i]]=struct.pack("<QH",BASE+reg.live.VTABLE,i)+b"\0"*6
    return slots,objects


class FakeConn:
    def __init__(self,slots,objects):
        self.slots=struct.pack(f"<{reg.SLOTS}Q",*slots)
        self.objects=objects
        self.buf=bytearray()
        self.sent=[]
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def settimeout(self,v):pass
    def sendall(self,data):
        self.sent.append(bytes(data))
        magic,cmd,size=struct.unpack_from("<III",data)
        assert cmd==0xBDAA0002, hex(cmd)
        pid,addr,length=struct.unpack_from("<IQI",data,12)
        reg_start=BASE+reg.REGISTRY_RVA
        if reg_start<=addr<reg_start+len(self.slots):
            body=self.slots[addr-reg_start:addr-reg_start+length]
        else:
            body=self.objects[addr][:length]
        self.buf+=struct.pack("<I",OK)+body
    def recv(self,n):
        out=bytes(self.buf[:n]);del self.buf[:n];return out


class TestRegistryProbe(unittest.TestCase):
    def run_probe(self,conn,report=None):
        with patch.object(reg.live,"check_live",return_value=report or live_report()), \
             patch.object(reg.socket,"create_connection",return_value=conn):
            return reg.probe("192.168.1.181")

    def test_01_live_layout_classified(self):
        slots,objects=fixture()
        conn=FakeConn(slots,objects)
        result=self.run_probe(conn)
        self.assertEqual(result["fiPackfile8_with_matching_index"],4)
        self.assertEqual(result["other_objects"],1)
        self.assertEqual(result["other_vtable_rvas"],["0x066B2018"])
        self.assertTrue(result["registry_hypothesis_supported"])
        self.assertFalse(result["game_memory_modified"])
        self.assertEqual(len(conn.sent),8+5)
        self.assertEqual(result["game_bytes_read"],1005+4096+5*16)

    def test_02_profile_mismatch_prevents_any_registry_read(self):
        with patch.object(reg.live,"check_live",return_value=live_report(False)), \
             patch.object(reg.socket,"create_connection") as conn:
            with self.assertRaisesRegex(ValueError,"registre non lu"):
                reg.probe("192.168.1.181")
            conn.assert_not_called()

    def test_03_wrong_index_or_vptr_not_counted(self):
        slots,objects=fixture()
        objects[slots[1]]=struct.pack("<QH",BASE+reg.live.VTABLE,9)+b"\0"*6
        objects[slots[2]]=struct.pack("<QH",0x1234,2)+b"\0"*6
        result=self.run_probe(FakeConn(slots,objects))
        self.assertEqual(result["fiPackfile8_with_matching_index"],2)
        self.assertEqual(result["other_objects"],3)

    def test_04_object_reads_capped(self):
        slots=[0x300000000+i*0x40 for i in range(reg.SLOTS)]
        objects={p:struct.pack("<QH",BASE+reg.live.VTABLE,i)+b"\0"*6
                 for i,p in enumerate(slots)}
        conn=FakeConn(slots,objects)
        result=self.run_probe(conn)
        self.assertEqual(result["objects_checked"],reg.MAX_OBJECTS)
        self.assertEqual(len(conn.sent),8+reg.MAX_OBJECTS)
        self.assertEqual(result["unchecked_nonzero_slots"],reg.SLOTS-reg.MAX_OBJECTS)

    def test_05_misaligned_pointer_never_dereferenced(self):
        slots,objects=fixture()
        slots[7]=0x202000003
        conn=FakeConn(slots,objects)
        result=self.run_probe(conn)
        self.assertEqual(result["unchecked_nonzero_slots"],1)
        self.assertEqual(len(conn.sent),8+5)

    def test_06_registry_must_be_in_rw_image_region(self):
        with self.assertRaises(ValueError):
            reg.registry_region(BASE,REGIONS[:3])
        ro=REGIONS[:3]+((0x06E20000,0x08A38000,1),)
        with self.assertRaisesRegex(ValueError,"rw-"):
            reg.registry_region(BASE,ro)

    def test_07_read_size_allowlist(self):
        conn=FakeConn(*fixture())
        for length in (8,4096,17):
            with self.subTest(length=length),self.assertRaisesRegex(ValueError,"interdite"):
                reg.read_bytes(conn,PID,BASE+reg.REGISTRY_RVA,length)
        self.assertEqual(conn.sent,[])

    def test_08_empty_registry_is_not_support(self):
        result=self.run_probe(FakeConn([0]*reg.SLOTS,{}))
        self.assertFalse(result["registry_hypothesis_supported"])


if __name__=="__main__":
    unittest.main()
