"""Offline protocol tests; NEVER connects to the user's PS5 or LAN."""
from __future__ import annotations

import io
import socket
import subprocess
import struct
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ps5debug_ng_probe as probe  # noqa: E402

LAN_IP = "192.168.1.181"
SYNTHETIC_TAILSCALE_IP = "100.101.102.103"  # Example only, NEVER a real user device.


class FakeSocket:
    def __init__(self, data: bytes):
        self.incoming = bytearray(data)
        self.sent: list[bytes] = []
        self.timeout: float | None = None
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.closed = True

    def sendall(self, data: bytes):
        self.sent.append(bytes(data))

    def settimeout(self, value: float):
        self.timeout = value

    def recv(self, count: int) -> bytes:
        # Emulate fragmented TCP replies and premature disconnects.
        size = min(count, 2, len(self.incoming))
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data


class FakeUdp:
    def __init__(self):
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.responses = [
            (b"invalid", ("192.168.1.100", 1010)),
            (probe.DISCOVERY_MAGIC, ("203.0.113.15", 1010)),
            (probe.DISCOVERY_MAGIC, (LAN_IP, 1010)),
            (probe.DISCOVERY_MAGIC, (LAN_IP, 1010)),
        ]
        self.bound = None
        self.opt = None
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def bind(self, address):
        self.bound = address

    def setsockopt(self, *args):
        self.opt = args

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendto(self, raw, destination):
        self.sent.append((raw, destination))

    def recvfrom(self, nbytes):
        if self.responses:
            return self.responses.pop(0)
        raise socket.timeout()


def fake_server(*, branding: str = "ps5debug-NG by OSR v1.3.2",
                firmware: int = 1340, advertised_length: int | None = None,
                truncate: int = 0) -> FakeSocket:
    brand = (branding + "\0" + "1.1").encode("utf-8")
    length = len(brand) if advertised_length is None else advertised_length
    wire = struct.pack("<I", length) + brand + struct.pack("<H", firmware)
    if truncate:
        wire = wire[:truncate]
    return FakeSocket(wire)


class TestPs5DebugNgReadOnlyProbe(unittest.TestCase):
    def test_01_valid_server_returns_firmware_and_correct_branding(self):
        fake = fake_server()
        with patch.object(probe.socket, "create_connection", return_value=fake) as connect:
            output = probe.probe(LAN_IP)
        connect.assert_called_once_with((LAN_IP, 744), timeout=3.0)
        self.assertEqual(output["firmware"], "13.40")
        self.assertEqual(output["expected_firmware"], "13.40")
        self.assertEqual(output["service"], "ps5debug-NG by OSR v1.3.2")
        self.assertEqual(output["capability"], "1.1")
        self.assertTrue(output["firmware_matches_expected"])
        self.assertTrue(output["read_only_identity_test"])
        self.assertFalse(output["debug_attached"])
        self.assertFalse(output["game_memory_accessed"])
        self.assertFalse(output["plugin_injected"])
        self.assertEqual(fake.sent, [
            struct.pack("<III", 0xFFAABBCC, 0xBD000501, 0),
            struct.pack("<III", 0xFFAABBCC, 0xBD000500, 0),
        ])
        self.assertTrue(fake.closed)

    def test_02_other_firmware_is_reported_as_mismatch(self):
        fake = fake_server(firmware=1360)
        with patch.object(probe.socket, "create_connection", return_value=fake):
            result = probe.probe(LAN_IP)
        self.assertEqual(result["firmware"], "13.60")
        self.assertEqual(result["expected_firmware"], "13.40")
        self.assertFalse(result["firmware_matches_expected"])

    def test_03_wrong_service_identity_rejected_before_second_command(self):
        fake = fake_server(branding="unexpected-local-server")
        with patch.object(probe.socket, "create_connection", return_value=fake):
            with self.assertRaisesRegex(ValueError, "pas ps5debug"):
                probe.probe(LAN_IP)
        self.assertEqual(len(fake.sent), 1)

    def test_04_oversized_response_rejected_without_reading_payload(self):
        fake = fake_server(advertised_length=100000)
        with patch.object(probe.socket, "create_connection", return_value=fake):
            with self.assertRaisesRegex(ValueError, "branding inattendue"):
                probe.probe(LAN_IP)
        self.assertEqual(len(fake.sent), 1)

    def test_05_truncated_response_rejected(self):
        fake = fake_server(truncate=7)
        with patch.object(probe.socket, "create_connection", return_value=fake):
            with self.assertRaisesRegex(ConnectionError, "fermee"):
                probe.probe(LAN_IP)

    def test_06_public_loopback_or_malformed_addresses_rejected(self):
        for ip in ("8.8.8.8", "127.0.0.1", "255.255.255.255",
                   "1.2.3.4", "no-host", "192.168.1.0/24", "::1", ""):
            with self.subTest(address=ip):
                with self.assertRaises(ValueError):
                    probe.probe(ip)

    def test_07_no_write_or_process_command_allowed(self):
        fake = FakeSocket(b"")
        with self.assertRaisesRegex(ValueError, "Seules les commandes"):
            probe.request(fake, 0xBDAA0003)  # Process WRITE
        with self.assertRaisesRegex(ValueError, "Seules les commandes"):
            probe.request(fake, 0xBDBB0001)  # Debug ATTACH
        self.assertEqual(fake.sent, [])

    def test_08_discovery_sends_one_readonly_broadcast(self):
        fake = FakeUdp()
        with patch.object(probe.socket, "socket", return_value=fake):
            got = probe.discover(timeout=0.15)
        self.assertEqual(got, [LAN_IP])
        self.assertEqual(
            fake.sent, [(struct.pack("<I", 0xFFFFAAAA),
                         ("255.255.255.255", 1010))]
        )
        self.assertEqual(fake.bound, ("0.0.0.0", 0))

    def test_09_cli_wrong_fw_returns_nonzero(self):
        fake = fake_server(firmware=1200)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(probe.socket, "create_connection", return_value=fake), \
             redirect_stdout(out), redirect_stderr(err):
            status = probe.main(["--ip", LAN_IP])
        self.assertEqual(status, 4)
        self.assertIn('"firmware": "12.00"', out.getvalue())
        self.assertIn("firmware detecte different", err.getvalue())


    def test_10_shared_cgnat_address_never_accepted_by_default(self):
        with self.assertRaises(ValueError):
            probe.validate_local_ip(SYNTHETIC_TAILSCALE_IP)
        self.assertEqual(
            probe.validate_local_ip(SYNTHETIC_TAILSCALE_IP, tailscale=True),
            SYNTHETIC_TAILSCALE_IP
        )
        for bad in ("8.8.8.8", "192.168.1.181", "127.0.0.1"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                probe.validate_local_ip(bad, tailscale=True)

    def test_11_tailscale_route_must_match_exact_adapter(self):
        ok = subprocess.CompletedProcess([], 0, stdout="Tailscale\r\n", stderr="")
        with patch.object(probe.sys, "platform", "win32"), \
             patch.object(probe.subprocess, "run", return_value=ok) as run:
            probe.verify_tailscale_route(SYNTHETIC_TAILSCALE_IP)
            self.assertIn("Find-NetRoute", run.call_args.args[0][-1])
        for response in (
            subprocess.CompletedProcess([], 0, stdout="Ethernet\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="NotTailscale\n", stderr=""),
            subprocess.CompletedProcess([], 1, stdout="Tailscale\n", stderr="error"),
        ):
            with self.subTest(response=response), \
                 patch.object(probe.sys, "platform", "win32"), \
                 patch.object(probe.subprocess, "run", return_value=response):
                with self.assertRaisesRegex(ValueError, "interface Tailscale"):
                    probe.verify_tailscale_route(SYNTHETIC_TAILSCALE_IP)

    def test_12_bad_route_prevents_even_tcp_connection(self):
        with patch.object(probe, "verify_tailscale_route",
                          side_effect=ValueError("no tailscale route")), \
             patch.object(probe.socket, "create_connection") as connect:
            with self.assertRaisesRegex(ValueError, "no tailscale route"):
                probe.probe(SYNTHETIC_TAILSCALE_IP, tailscale=True)
            connect.assert_not_called()

    def test_13_tailscale_probe_only_version_requests(self):
        fake = fake_server()
        with patch.object(probe, "verify_tailscale_route") as verify, \
             patch.object(probe.socket, "create_connection", return_value=fake):
            answer = probe.probe(SYNTHETIC_TAILSCALE_IP, tailscale=True)
        verify.assert_called_once_with(SYNTHETIC_TAILSCALE_IP)
        self.assertEqual(answer["firmware"], "13.40")
        self.assertFalse(answer["game_memory_accessed"])
        self.assertEqual(fake.sent, [
            struct.pack("<III", 0xFFAABBCC, 0xBD000501, 0),
            struct.pack("<III", 0xFFAABBCC, 0xBD000500, 0),
        ])

    def test_14_tailscale_requires_explicit_ip_not_discovery(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
             patch.object(probe.socket, "socket") as udp:
            status = probe.main(["--discover", "--tailscale"])
        self.assertEqual(status, 2)
        self.assertIn("--tailscale s'utilise avec --ip", err.getvalue())
        udp.assert_not_called()

    def test_15_main_tailscale_path_never_writes_memory(self):
        fake = fake_server()
        out, err = io.StringIO(), io.StringIO()
        with patch.object(probe, "verify_tailscale_route") as verify, \
             patch.object(probe.socket, "create_connection", return_value=fake), \
             redirect_stdout(out), redirect_stderr(err):
            code = probe.main(["--ip", SYNTHETIC_TAILSCALE_IP, "--tailscale"])
        self.assertEqual(code, 0, err.getvalue())
        verify.assert_called_once_with(SYNTHETIC_TAILSCALE_IP)
        self.assertIn('"firmware_matches_expected": true', out.getvalue())
        self.assertEqual(len(fake.sent), 2)


    def test_16_optional_future_expected_firmware_can_be_selected(self):
        # Firmware selection is explicit; no process or memory operation.
        future = fake_server(firmware=1360)
        with patch.object(probe, "verify_tailscale_route"), \
             patch.object(probe.socket, "create_connection", return_value=future):
            answer = probe.probe(SYNTHETIC_TAILSCALE_IP, tailscale=True,
                                 expected_fw=1360)
        self.assertEqual(answer["firmware"], "13.60")
        self.assertEqual(answer["expected_firmware"], "13.60")
        self.assertTrue(answer["firmware_matches_expected"])
        self.assertEqual(len(future.sent), 2)

    def test_17_bad_expected_firmware_refused(self):
        for text in ("", "13.4", "13", "13.400", "0.00", "25.00", "13.40;echo"):
            with self.subTest(value=text), self.assertRaises(Exception):
                probe.parse_expected_fw(text)
        with patch.object(probe.socket, "create_connection") as conn:
            with self.assertRaisesRegex(ValueError, "Firmware attendu incorrect"):
                probe.probe(LAN_IP, expected_fw=9999)
            conn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
