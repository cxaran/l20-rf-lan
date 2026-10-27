"""Synthetic transport tests: no LAN, real credential or RF is accessed."""
import base64
from dataclasses import FrozenInstanceError
import json
import math
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

import rf_device as rf

KEY, DEVICE = b"0123456789abcdef", "synthetic-device"
HOST, MAC = "10.23.45.67", "02:00:00:00:00:10"
CREDENTIAL = rf.Credentials(HOST, MAC, DEVICE, KEY)
ORIGINAL_CHECK_MAC = rf._check_mac
ORIGINAL_LOAD_CREDENTIALS = rf.load_credentials


def config_for(**changes):
    value = {"target_ip": HOST, "target_mac": MAC, "device_id": DEVICE,
             "local_key": KEY.decode(), "port": 6668, "version": "3.3"}
    value.update(changes)
    return value


def code_for(**changes):
    obj = {"ver": "2", "num": 1, "data0": base64.b64encode(b"synthetic pulses").decode(),
           "lv": [0], "study_feq": "433.92"}
    obj.update(changes)
    return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()


def response(sequence=41, command=7, obj=None, retcode=0, payload=None):
    if payload is None:
        payload = b"" if obj is None else rf._VERSION + rf._cipher(KEY).encrypt(
            json.dumps(obj, separators=(",", ":")).encode(), use_base64=False)
    body = struct.pack(">I", retcode) + payload
    raw = struct.pack(">4I", 0x55AA, sequence, command, len(body) + 8) + body
    return raw + struct.pack(">2I", zlib.crc32(raw) & 0xffffffff, 0xAA55)


def request_body(raw):
    assert struct.unpack_from(">I", raw, 8)[0] == 7
    assert zlib.crc32(raw[:-8]) & 0xffffffff == struct.unpack_from(">I", raw, len(raw) - 8)[0]
    encrypted = raw[16:-8]
    assert encrypted.startswith(rf._VERSION)
    return json.loads(rf._cipher(KEY).decrypt(encrypted[15:], use_base64=False,
        decode_text=True, verify_padding=True))


class Clock:
    def __init__(self):
        self.now = 100.0
    def __call__(self):
        return self.now


class FakeSocket:
    def __init__(self, clock):
        self.clock, self.chunks, self.writes = clock, [], []
        self.connects, self.closed = [], False
        self.write_error = None
        self.on_recv = None
    def settimeout(self, value):
        self.timeout = value
    def connect(self, address):
        self.connects.append(address)
    def sendall(self, data):
        self.writes.append(data)
        if self.write_error:
            raise self.write_error
    def recv(self, size):
        if self.on_recv:
            self.on_recv()
        if not self.chunks:
            self.clock.now += .21
            raise socket.timeout()
        item = self.chunks.pop(0)
        self.clock.now += .001
        if isinstance(item, Exception):
            self.clock.now += .21
            raise item
        if len(item) > size:
            self.chunks.insert(0, item[size:])
            item = item[:size]
        return item
    def close(self):
        self.closed = True


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sock = FakeSocket(self.clock)
        self.patches = [patch.object(rf.time, "monotonic", self.clock),
            patch.object(rf, "load_credentials", return_value=CREDENTIAL),
            patch.object(rf, "_check_mac"),
            patch.object(rf.socket, "socket", return_value=self.sock),
            patch.object(rf.secrets, "randbelow", return_value=41)]
        self.mocks = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.radio = rf.Radio("synthetic.dpapi")

    def test_construction_has_no_effects(self):
        self.mocks[1].assert_not_called()
        self.mocks[2].assert_not_called()
        self.mocks[3].assert_not_called()

    def test_credentials_are_canonical_frozen_and_safe_to_represent(self):
        value = rf.validate_credentials(config_for(target_ip=" 10.23.45.67 ",
            target_mac="02:ab:cd:ef:00:10", local_key="é" * 16, version=3.3))
        self.assertEqual(value.target_ip, HOST)
        self.assertEqual(value.target_mac, "02:AB:CD:EF:00:10")
        self.assertEqual(value.local_key, b"\xe9" * 16)
        self.assertEqual((value.port, value.version), (6668, "3.3"))
        self.assertNotIn(DEVICE, repr(value))
        self.assertNotIn("local_key", repr(value))
        with self.assertRaises(FrozenInstanceError):
            value.target_ip = "10.23.45.68"
        defaults = config_for()
        defaults.pop("port")
        defaults.pop("version")
        self.assertEqual(rf.validate_credentials(defaults), CREDENTIAL)
        self.mocks[3].assert_not_called()

    def test_invalid_configuration_is_rejected_without_leaking_values(self):
        changes = [
            {"target_ip": host} for host in ("127.0.0.1", "0.0.0.0", "224.0.0.1",
                "240.0.0.1", "255.255.255.255", "8.8.8.8", "::1", "localhost", "", None)
        ]
        changes += [{"target_mac": mac} for mac in ("bad", "00:00:00:00:00:00",
            "FF:FF:FF:FF:FF:FF", "01:00:00:00:00:10", "02-00-00-00-00-10", None)]
        changes += [{"port": port} for port in (0, 6669, True, "6668", 6668.0)]
        changes += [{"version": version} for version in (3.4, "3.5", True, None)]
        changes += [{"device_id": "synthetic secret invalid id"}, {"device_id": ""},
            {"local_key": "short"}, {"local_key": "x" * 17}, {"local_key": "😀" * 16},
            {"local_key": KEY}]
        for change in changes:
            with self.subTest(fields=tuple(change)):
                with self.assertRaises(rf.RfError) as caught:
                    rf.validate_credentials(config_for(**change))
                self.assertEqual(caught.exception.code, "INVALID_CREDENTIALS")
                self.assertNotIn("synthetic secret", str(caught.exception))
        for value in (None, [], {}, "invalid"):
            with self.assertRaises(rf.RfError):
                rf.validate_credentials(value)
        self.mocks[3].assert_not_called()

    def test_two_radio_destinations_are_read_from_each_config(self):
        other = rf.validate_credentials(config_for(target_ip="172.20.10.8",
            target_mac="02:00:00:00:00:20", device_id="second-synthetic-device"))
        second_socket = FakeSocket(self.clock)
        self.sock.chunks, second_socket.chunks = [response()], [response()]
        self.mocks[1].side_effect = [CREDENTIAL, other]
        self.mocks[3].side_effect = [self.sock, second_socket]
        first = self.radio.send(code_for())
        second = rf.Radio("second.dpapi").send(code_for())
        self.assertEqual((first["outcome"], second["outcome"]), ("ACKNOWLEDGED", "ACKNOWLEDGED"))
        self.assertEqual(self.sock.connects, [(HOST, 6668)])
        self.assertEqual(second_socket.connects, [(other.target_ip, 6668)])
        self.assertEqual([call.args[:2] for call in self.mocks[2].call_args_list],
            [(HOST, MAC), (other.target_ip, other.target_mac)])
        self.assertEqual([call.args[0] for call in self.mocks[1].call_args_list],
            [Path("synthetic.dpapi"), Path("second.dpapi")])
        self.assertEqual(request_body(self.sock.writes[0])["devId"], DEVICE)
        self.assertEqual(request_body(second_socket.writes[0])["devId"], other.device_id)
        self.assertEqual((len(self.sock.writes), len(second_socket.writes)), (1, 1))
        self.assertFalse(hasattr(rf, "HOST"))
        self.assertFalse(hasattr(rf, "MAC"))

    def test_capture_uses_selected_destination_for_start_and_exit(self):
        other = rf.validate_credentials(config_for(target_ip="172.20.10.8",
            target_mac="02:00:00:00:00:20", device_id="second-synthetic-device"))
        self.mocks[1].return_value = other
        self.sock.chunks = [response(command=8, obj={"dps": {"202": code_for()}})]
        result = self.radio.capture(threading.Event(), None)
        self.assertEqual(result["source_dp"], "202")
        self.assertEqual(self.sock.connects, [(other.target_ip, 6668)])
        self.assertEqual(self.mocks[2].call_args.args[:2], (other.target_ip, other.target_mac))
        self.assertEqual([request_body(raw)["devId"] for raw in self.sock.writes],
            [other.device_id, other.device_id])
        self.assertEqual(len(self.sock.writes), 2)

    def test_arp_worker_checks_requested_host_and_expected_mac(self):
        with patch.object(rf, "_arp_mac", return_value=MAC) as arp:
            ORIGINAL_CHECK_MAC(HOST, MAC, self.clock.now + 1)
            arp.assert_called_once_with(HOST)
        other_host, other_mac = "172.20.10.8", "02:00:00:00:00:20"
        with patch.object(rf, "_arp_mac", return_value=other_mac) as arp:
            ORIGINAL_CHECK_MAC(other_host, other_mac, self.clock.now + 1)
            arp.assert_called_once_with(other_host)
        self.mocks[3].assert_not_called()

    def test_public_load_credentials_reads_synthetic_dpapi_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.dpapi"
            path.write_bytes(rf.seal(json.dumps(config_for()).encode()))
            self.assertEqual(ORIGINAL_LOAD_CREDENTIALS(path), CREDENTIAL)
            with patch.object(rf, "load_credentials", wraps=ORIGINAL_LOAD_CREDENTIALS):
                self.assertEqual(rf.credential_info(path), {"host": HOST, "mac": MAC,
                    "port": 6668, "version": "3.3", "ready": True})
        self.mocks[3].assert_not_called()

    def test_code_roundtrip_and_safe_summary(self):
        code = code_for()
        value = rf.validate_code(" \n" + code + "\n ")
        self.assertEqual(value["canonical_code"], code)
        self.assertEqual(value["summary"], {"version": "2", "num": 1,
            "frequency": 433.92, "length": len(code)})
        self.assertNotIn("data0", repr(value["summary"]))

    def test_strict_container_validation(self):
        bad = ["", "%%%", code_for(ver="3"), code_for(num=True), code_for(num=1.0),
            code_for(num=2), code_for(lv=None), code_for(lv=[True]), code_for(lv=[2]),
            code_for(data0="A===") , code_for(data1="YQ=="),
            code_for(study_feq="nan"), code_for(study_feq=4333)]
        duplicate = '{"ver":"2","num":1,"num":1,"data0":"YQ==","lv":[0]}'
        bad.append(base64.b64encode(duplicate.encode()).decode())
        for code in bad:
            with self.subTest(length=len(code)):
                with self.assertRaises(rf.RfError) as caught:
                    rf.validate_code(code)
                self.assertEqual(caught.exception.code, "INVALID_INPUT")

    def test_credential_info_only_safe_metadata(self):
        self.assertEqual(rf.credential_info("unused"), {
            "host": HOST, "mac": MAC, "port": 6668, "version": "3.3", "ready": True})
        with patch.object(rf, "load_credentials", side_effect=rf.RfError("INVALID_CREDENTIALS")):
            self.assertEqual(rf.credential_info("unused"), {
                "host": "", "mac": "", "port": None, "version": "", "ready": False})
        self.mocks[2].assert_not_called()
        self.mocks[3].assert_not_called()

    def test_send_one_write_ack_only(self):
        self.sock.chunks = [response()]
        value = self.radio.send(code_for(), times=6)
        self.assertEqual(value, {"outcome": "ACKNOWLEDGED", "problem": "NONE",
            "frame_write_attempted": True, "physical_verified": False, "times": 6,
            "timing_ms": {"prepare": 0.0, "arp": 0.0, "connect": 0.0,
                "write": 0.0, "response": 1.0, "total": 1.0}})
        self.assertEqual(self.sock.connects, [(HOST, 6668)])
        self.assertEqual(len(self.sock.writes), 1)
        command = json.loads(request_body(self.sock.writes[0])["dps"]["201"])
        self.assertEqual(command["control"], "rfstudy_send")
        self.assertEqual(command["key1"]["times"], 6)
        self.assertEqual(set(command["key1"]), {"code", "times", "delay", "intervals"})
        self.assertTrue(self.sock.closed)

    def assert_safe_timing(self, value):
        self.assertEqual(set(value), {"outcome", "problem", "frame_write_attempted",
                                     "physical_verified", "times", "timing_ms"})
        self.assertEqual(type(value["times"]), int)
        self.assertIn(value["times"], range(1, 7))
        timing = value["timing_ms"]
        self.assertEqual(set(timing), {"prepare", "arp", "connect", "write", "response", "total"})
        self.assertIsNotNone(timing["total"])
        for duration in timing.values():
            if duration is not None:
                self.assertIn(type(duration), (int, float))
                self.assertTrue(math.isfinite(duration))
                self.assertGreaterEqual(duration, 0)

    def test_lab_measures_each_phase_and_total_includes_close(self):
        def credentials(_):
            self.clock.now += .003
            return CREDENTIAL
        def arp(host, mac, deadline):
            self.clock.now += .020
        connect, write, close = self.sock.connect, self.sock.sendall, self.sock.close
        def delayed_connect(address):
            self.clock.now += .030
            connect(address)
        def delayed_write(data):
            self.clock.now += .004
            write(data)
        def delayed_close():
            self.clock.now += .002
            close()
        self.mocks[1].side_effect = credentials
        self.mocks[2].side_effect = arp
        self.sock.chunks = [response()]
        with patch.object(self.sock, "connect", side_effect=delayed_connect), \
             patch.object(self.sock, "sendall", side_effect=delayed_write), \
             patch.object(self.sock, "close", side_effect=delayed_close):
            value = self.radio.send(code_for())
        self.assert_safe_timing(value)
        self.assertEqual(value["timing_ms"], {"prepare": 3.0, "arp": 20.0,
            "connect": 30.0, "write": 4.0, "response": 1.0, "total": 60.0})
        self.assertEqual(len(self.sock.writes), 1)
        self.assertEqual(self.sock.connects, [(HOST, 6668)])

    def test_lab_progress_after_write_before_response_and_callback_errors_ignored(self):
        events = []
        def progress(message):
            events.append((message, len(self.sock.writes)))
            raise RuntimeError("synthetic private callback detail")
        self.sock.on_recv = lambda: events.append(("read", len(self.sock.writes)))
        self.sock.chunks = [response()]
        value = self.radio.send(code_for(), progress=progress)
        self.assertEqual(events, [("Orden enviada al L20; esperando respuesta.", 1), ("read", 1)])
        self.assertEqual(value["outcome"], "ACKNOWLEDGED")
        self.assert_safe_timing(value)
        self.assertNotIn("private callback", repr(value))
        self.assertEqual(len(self.sock.writes), 1)

    def test_lab_failed_write_records_reached_phases_without_progress(self):
        self.sock.write_error = OSError("synthetic detail")
        notices = []
        value = self.radio.send(code_for(), progress=notices.append)
        self.assertEqual(value["outcome"], "UNCERTAIN")
        self.assertTrue(value["frame_write_attempted"])
        self.assertEqual(notices, [])
        self.assert_safe_timing(value)
        self.assertIsNotNone(value["timing_ms"]["write"])
        self.assertIsNone(value["timing_ms"]["response"])
        self.assertEqual(len(self.sock.writes), 1)
        self.assertEqual(len(self.sock.connects), 1)

    def test_lab_not_sent_timing_has_no_unreached_phases(self):
        invalid = self.radio.send(code_for(), times=True)
        self.assert_safe_timing(invalid)
        self.assertEqual(invalid["times"], 1)
        self.assertEqual(invalid["outcome"], "NOT_SENT")
        self.assertIsNotNone(invalid["timing_ms"]["prepare"])
        for name in ("arp", "connect", "write", "response"):
            self.assertIsNone(invalid["timing_ms"][name])
        with rf._RADIO_LOCK:
            busy = self.radio.send(code_for())
        self.assert_safe_timing(busy)
        self.assertEqual(busy["problem"], "BUSY")
        for name in ("prepare", "arp", "connect", "write", "response"):
            self.assertIsNone(busy["timing_ms"][name])
        self.mocks[3].assert_not_called()

    def test_lab_actual_default_send_bytes_match_independent_sdk(self):
        import tinytuya
        from tinytuya.core import CONTROL
        device = tinytuya.Device(DEVICE, address=HOST, local_key=KEY.decode(), version=3.3)
        device.seqno = 41
        code = code_for()
        command = {"control": "rfstudy_send", "rf_type": "sub_2g", "feq": 0,
            "mode": 0, "rate": 0, "ver": "2", "key1": {
                "code": code, "times": 1, "delay": 0, "intervals": 0}}
        self.sock.chunks = [response()]
        with patch.object(rf.time, "time", return_value=1700000000):
            payload = device.generate_payload(CONTROL, {"201": json.dumps(command, separators=(",", ":"))})
            expected = device._encode_message(payload)
            value = self.radio.send(code)
        self.assertEqual(self.sock.writes, [expected])
        self.assertEqual(self.sock.connects, [(HOST, 6668)])
        self.assertEqual(value["times"], 1)
        self.assert_safe_timing(value)

    def test_frame_matches_independent_tinytuya_encoder(self):
        import tinytuya
        from tinytuya.core import CONTROL
        # Supplying address/key/version prevents discovery. No send/socket API
        # is called: SDK payload/encoder are the independent wire reference.
        device = tinytuya.Device(DEVICE, address=HOST, local_key=KEY.decode(),
                                version=3.3, dev_type="default")
        commands = [
            {"control": "rf_study", "rf_type": "sub_2g", "study_feq": "0", "ver": "2"},
            {"control": "rfstudy_exit", "rf_type": "sub_2g", "study_feq": "433.92", "ver": "2"},
            {"control": "rfstudy_send", "rf_type": "sub_2g", "feq": 0,
             "mode": 0, "rate": 0, "ver": "2", "key1": {
                 "code": code_for(), "times": 1, "delay": 0, "intervals": 0}},
        ]
        with patch.object(rf.time, "time", return_value=1700000000):
            for command in commands:
                device.seqno = 123
                payload = device.generate_payload(CONTROL, {
                    "201": json.dumps(command, separators=(",", ":"))})
                expected = device._encode_message(payload)
                self.assertEqual(rf._frame(command, DEVICE, KEY, 123), expected)
        self.mocks[3].assert_not_called()

    def test_decode_nonzero_reserved_header_matches_tinytuya(self):
        import tinytuya
        from tinytuya.core.crypto_helper import AESCipher
        device = tinytuya.Device(DEVICE, address=HOST, local_key=KEY.decode(),
                                version=3.3, dev_type="default")
        expected = {"dps": {"202": "synthetic-report"}}
        encrypted = AESCipher(KEY).encrypt(json.dumps(expected).encode(), False)
        payload = b"3.3" + bytes(range(1, 13)) + encrypted
        self.assertEqual(device._decode_payload(payload), expected)
        self.assertEqual(rf._decode(payload, KEY), expected)
        self.mocks[3].assert_not_called()

    def test_decode_rejects_truncated_and_invalid_payload(self):
        for payload in (b"3.3", b"3.3" + bytes(5), b"3.3" + bytes(12),
                        b"3.3" + bytes(12) + b"truncated", bytes(16)):
            with self.subTest(length=len(payload)):
                with self.assertRaises(rf.RfError) as caught:
                    rf._decode(payload, KEY)
                self.assertEqual(caught.exception.code, "KEY_OR_VERSION")
        self.mocks[3].assert_not_called()

    def test_decode_keeps_strict_pkcs7_padding(self):
        from tinytuya.core.crypto_helper import AESCipher
        plain = b'{"dps":{}}'
        pad = 16 - len(plain) % 16
        # A valid final length byte with incorrect preceding padding bytes must
        # remain rejected even when the reserved header bytes are accepted.
        malformed = plain + b"X" * (pad - 1) + bytes([pad])
        payload = b"3.3" + bytes(range(1, 13)) + AESCipher(KEY).encrypt(
            malformed, use_base64=False, pad=False)
        with self.assertRaises(rf.RfError) as caught:
            rf._decode(payload, KEY)
        self.assertEqual(caught.exception.code, "KEY_OR_VERSION")
        self.mocks[3].assert_not_called()

    def test_send_invalid_times_never_connect(self):
        for times in (True, 0, 7, "1", 1.0):
            value = self.radio.send(code_for(), times)
            self.assertEqual(value["outcome"], "NOT_SENT")
            self.assertFalse(value["frame_write_attempted"])
        self.mocks[3].assert_not_called()

    def test_partial_write_is_uncertain_and_never_retried(self):
        self.sock.write_error = OSError("synthetic secret must not escape")
        value = self.radio.send(code_for())
        self.assertEqual(value["outcome"], "UNCERTAIN")
        self.assertEqual(value["problem"], "IO")
        self.assertEqual(len(self.sock.writes), 1)
        self.assertEqual(len(self.sock.connects), 1)
        self.assertNotIn("synthetic secret", repr(value))

    def test_send_timeout_is_uncertain(self):
        value = self.radio.send(code_for())
        self.assertEqual(value["problem"], "TIMEOUT")
        self.assertEqual(value["outcome"], "UNCERTAIN")
        self.assertEqual(len(self.sock.writes), 1)

    def test_send_filters_unrelated_frames(self):
        self.sock.chunks = [response(sequence=99) + response(command=8) + response()]
        self.assertEqual(self.radio.send(code_for())["outcome"], "ACKNOWLEDGED")

    def test_device_rejections(self):
        for frame in (response(retcode=1), response(obj={"success": False}),
                      response(obj={"error": "synthetic detail"})):
            self.sock.chunks = [frame]
            value = self.radio.send(code_for())
            self.assertEqual(value["outcome"], "DEVICE_REJECTED")
            self.assertFalse(value["physical_verified"])

    def test_fragmented_big_capture_and_exit_once(self):
        code = code_for(data0=base64.b64encode(bytes(6000)).decode())
        frame = response(sequence=90, command=8, obj={"data": {"dps": {"202": code}}})
        self.sock.chunks = [frame[:7], socket.timeout(), frame[7:1500], socket.timeout(), frame[1500:]]
        progress = []
        value = self.radio.capture(threading.Event(), progress.append)
        self.assertEqual(value["code"], code)
        self.assertEqual(value["source_dp"], "202")
        self.assertEqual(value["origin"], "received_during_learning")
        self.assertFalse(value["physical_verified"])
        self.assertTrue(value["learning_exit_sent"])
        self.assertEqual(len(self.sock.connects), 1)
        commands = [json.loads(request_body(x)["dps"]["201"])["control"] for x in self.sock.writes]
        self.assertEqual(commands, ["rf_study", "rfstudy_exit"])
        self.assertTrue(progress)
        self.assertTrue(self.sock.closed)

    def test_capture_dp2_and_crc_resynchronization(self):
        bad = bytearray(response(obj={"dps": {"202": code_for()}}))
        bad[-8] ^= 1
        self.sock.chunks = [b"noise" + bytes(bad) + response(command=8, obj={"dps": {"2": code_for()}})]
        self.assertEqual(self.radio.capture(threading.Event(), None)["source_dp"], "2")

    def test_cancel_before_capture_has_no_network(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(rf.RfError) as caught:
            self.radio.capture(cancel, None)
        self.assertEqual(caught.exception.code, "CANCELLED")
        self.mocks[2].assert_not_called()
        self.mocks[3].assert_not_called()

    def test_cancel_during_capture_exits_same_connection(self):
        cancel = threading.Event()
        self.sock.on_recv = cancel.set
        with self.assertRaises(rf.RfError) as caught:
            self.radio.capture(cancel, None)
        self.assertEqual(caught.exception.code, "CANCELLED")
        self.assertTrue(caught.exception.cleanup_sent)
        self.assertEqual(len(self.sock.writes), 2)
        self.assertEqual(len(self.sock.connects), 1)

    def test_capture_eof_and_timeout_cleanup(self):
        self.sock.chunks = [b""]
        with self.assertRaises(rf.RfError) as caught:
            self.radio.capture(threading.Event(), None)
        self.assertEqual(caught.exception.code, "REMOTE_EOF")
        self.assertTrue(caught.exception.cleanup_sent)
        self.sock.chunks, self.sock.writes = [], []
        with self.assertRaises(rf.RfError) as caught:
            self.radio.capture(threading.Event(), None, seconds=1)
        self.assertIn(caught.exception.code, ("NO_CODE", "TIMEOUT"))
        self.assertEqual(len(self.sock.writes), 2)

    def test_failed_start_still_attempts_exit_no_reconnect(self):
        self.sock.write_error = OSError("private detail")
        with self.assertRaises(rf.RfError) as caught:
            self.radio.capture(threading.Event(), None)
        self.assertEqual(caught.exception.code, "IO")
        self.assertFalse(caught.exception.cleanup_sent)
        self.assertEqual(len(self.sock.writes), 2)
        self.assertEqual(len(self.sock.connects), 1)

    def test_operation_lock_blocks_overlap(self):
        with rf._RADIO_LOCK:
            self.assertEqual(self.radio.send(code_for())["problem"], "BUSY")
            with self.assertRaises(rf.RfError) as caught:
                self.radio.capture(threading.Event(), None)
            self.assertEqual(caught.exception.code, "BUSY")
        self.mocks[3].assert_not_called()

    def test_arp_checks_cancel_and_mac_without_tcp(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(rf, "_arp_mac") as arp:
            with self.assertRaises(rf.RfError):
                ORIGINAL_CHECK_MAC(HOST, MAC, self.clock.now + 1, cancel)
            arp.assert_not_called()
        with patch.object(rf, "_arp_mac", return_value="00:00:00:00:00:00"):
            with self.assertRaises(rf.RfError) as caught:
                ORIGINAL_CHECK_MAC(HOST, MAC, self.clock.now + 1)
            self.assertEqual(caught.exception.code, "MAC_MISMATCH")
        self.mocks[3].assert_not_called()

    def test_native_dpapi_roundtrip_synthetic_only(self):
        payload = b"synthetic-storage-roundtrip"
        sealed = rf.seal(payload)
        self.assertNotIn(payload, sealed)
        self.assertEqual(rf.unseal(sealed), payload)
        self.mocks[3].assert_not_called()

    def test_credentials_validate_destination_no_secret_error(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "synthetic.dpapi"
            file.write_bytes(b"synthetic sealed bytes")
            credential = {"target_ip": HOST, "target_mac": MAC,
                "device_id": DEVICE, "local_key": KEY.decode()}
            # Execute the real credential reader, replacing only native unseal.
            original = self.mocks[1].side_effect
            self.patches[1].stop()
            try:
                with patch.object(rf, "unseal", return_value=json.dumps(credential).encode()):
                    self.assertTrue(rf.credential_info(file)["ready"])
                credential["target_ip"] = "8.8.8.8"
                with patch.object(rf, "unseal", return_value=json.dumps(credential).encode()):
                    self.assertFalse(rf.credential_info(file)["ready"])
            finally:
                self.patches[1].start().side_effect = original


if __name__ == "__main__":
    unittest.main()
