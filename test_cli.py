"""CLI con datos sintéticos y DPAPI temporal. Sin red, receptor ni capturas reales."""
from __future__ import annotations

import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import app
import l20
import rf_device


def synthetic_container(marker="AQIDBA=="):
    return {"num": 1, "ver": "2", "study_feq": "433.92", "data0": marker, "lv": [0]}


def synthetic_code(marker="AQIDBA=="):
    raw = json.dumps(synthetic_container(marker), separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


@unittest.skipUnless(os.name == "nt", "El CLI usa DPAPI de Windows.")
class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="l20-cli-synthetic-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "capturas"
        self.credentials = self.root / ".private" / "l20.dpapi"
        self.library = app.Library(self.directory)
        self.synthetic_credentials = {
            "target_ip": "10.23.45.67", "target_mac": "02:00:00:23:45:67",
            "device_id": "synthetic_cli_device_001", "local_key": "0123456789ABCDEF",
            "port": 6668, "version": "3.3",
        }
        # Falla antes de cualquier socket o ARP si una ruta supuestamente pasiva
        # intenta contactar con un equipo. Los Radio de pruebas son mocks.
        for target in ("rf_device.socket.create_connection", "rf_device.socket.socket", "rf_device._arp_mac"):
            guard = patch(target, side_effect=AssertionError("La prueba no permite red ni ARP."))
            guard.start()
            self.addCleanup(guard.stop)
        radio_guard = patch("l20.Radio", side_effect=AssertionError("Radio no debe construirse aquí."))
        self.radio_factory = radio_guard.start()
        self.addCleanup(radio_guard.stop)

    def invoke(self, arguments, *, with_data=True):
        options = ["--credentials", str(self.credentials)]
        if with_data:
            options += ["--data", str(self.directory)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = l20.main(options + list(arguments))
        return result, stdout.getvalue(), stderr.getvalue()

    def code_file(self, name="signal.txt", marker="AQIDBA==", *, as_json=False):
        path = self.root / name
        text = json.dumps(synthetic_container(marker), indent=2) if as_json else synthetic_code(marker)
        path.write_text(text, encoding="utf-8")
        return path

    def save_record(self, *, name="Control sintético", notes="Nota sintética"):
        source = self.code_file()
        status, stdout, stderr = self.invoke(["save", "--name", name, "--notes", notes, "--file", str(source)])
        self.assertEqual((status, stderr), (0, ""))
        return self.library.get(json.loads(stdout)["id"])

    def fake_radio(self):
        radio = Mock(spec=("capture", "send"))
        self.radio_factory.side_effect = None
        self.radio_factory.return_value = radio
        return radio

    def send_result(self, outcome="ACKNOWLEDGED", problem="NONE"):
        return {"outcome": outcome, "problem": problem, "frame_write_attempted": True,
                "physical_verified": False, "times": 4,
                "timing_ms": {"prepare": 1, "arp": 2, "connect": 3, "write": 4, "response": 5, "total": 15}}

    def assert_no_capture_files(self):
        self.assertEqual(list(self.directory.glob("*.dpapi")), [])

    def test_configure_prompts_hide_secrets_and_dpapi_round_trip(self):
        value = self.synthetic_credentials
        with patch("builtins.input", side_effect=[" " + value["target_ip"] + " ", value["target_mac"].lower()]) as inputs, \
                patch("l20.getpass.getpass", side_effect=[value["device_id"], value["local_key"]]) as hidden:
            status, stdout, stderr = self.invoke(["configure"])
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(inputs.call_count, 2)
        self.assertEqual(hidden.call_count, 2)
        for secret in (value["device_id"], value["local_key"]):
            self.assertNotIn(secret, stdout + stderr)
            self.assertNotIn(secret.encode(), self.credentials.read_bytes())
        loaded = rf_device.load_credentials(self.credentials)
        self.assertEqual(loaded.target_ip, value["target_ip"])
        self.assertEqual(loaded.target_mac, value["target_mac"])
        self.assertEqual(loaded.device_id, value["device_id"])
        self.assertEqual(loaded.local_key, value["local_key"].encode("ascii"))
        self.radio_factory.assert_not_called()
        self.assertEqual(list(self.credentials.parent.glob("*.tmp")), [])

    def test_configure_existing_file_is_preserved_without_prompting(self):
        self.credentials.parent.mkdir()
        self.credentials.write_bytes(b"synthetic existing credential")
        with patch("builtins.input") as inputs, patch("l20.getpass.getpass") as hidden:
            status, stdout, stderr = self.invoke(["configure"])
        self.assertEqual(status, 2)
        self.assertIn("--replace", stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(self.credentials.read_bytes(), b"synthetic existing credential")
        inputs.assert_not_called()
        hidden.assert_not_called()
        self.radio_factory.assert_not_called()

    def test_configure_invalid_input_leaves_no_credential(self):
        with patch("builtins.input", side_effect=["not-an-address", self.synthetic_credentials["target_mac"]]), \
                patch("l20.getpass.getpass", side_effect=["synthetic_id", "0123456789ABCDEF"]):
            status, stdout, stderr = self.invoke(["configure"])
        self.assertEqual(status, 2)
        self.assertFalse(self.credentials.exists())
        self.assertNotIn("0123456789ABCDEF", stdout + stderr)
        self.radio_factory.assert_not_called()

    def test_save_base64_and_json_list_omits_codes_and_export_is_explicit(self):
        records = []
        for as_json, name in ((False, "base64.txt"), (True, "container.json")):
            source = self.code_file(name, as_json=as_json)
            status, stdout, stderr = self.invoke(["save", "--name", name, "--file", str(source)])
            self.assertEqual((status, stderr), (0, ""))
            record = json.loads(stdout)
            self.assertNotIn("code", record)
            records.append(record)
        status, stdout, stderr = self.invoke(["list"])
        listing = json.loads(stdout)
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(len(listing["captures"]), 2)
        self.assertEqual(listing["unreadable_captures"], 0)
        for record in listing["captures"]:
            self.assertNotIn("code", record)
        self.assertNotIn(synthetic_code(), stdout)
        exported = self.root / "exports" / "signal.txt"
        status, stdout, stderr = self.invoke(["export", records[0]["id"], "--output", str(exported)])
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(exported.read_text(encoding="ascii"), synthetic_code() + "\n")
        self.assertNotIn(synthetic_code(), stdout)
        self.assertIn("texto claro", stdout)
        self.radio_factory.assert_not_called()

    def test_export_refuses_overwrite_and_preserves_existing_file(self):
        record = self.save_record()
        exported = self.root / "existing.txt"
        exported.write_text("synthetic original export", encoding="ascii")
        status, stdout, stderr = self.invoke(["export", record["id"], "--output", str(exported)])
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("no se sobrescriben", stderr)
        self.assertEqual(exported.read_text(encoding="ascii"), "synthetic original export")
        self.radio_factory.assert_not_called()

    def test_save_id_edits_revision_notes_and_resets_verification_only_for_changed_code(self):
        record = self.save_record()
        verified = self.library.verify(record["id"], record["revision"], app.code_hash(record["code"]), True)
        original = self.code_file("same.txt")
        status, stdout, stderr = self.invoke(["save", "--id", record["id"], "--name", "Renombrado", "--file", str(original)])
        self.assertEqual((status, stderr), (0, ""))
        renamed = self.library.get(record["id"])
        self.assertEqual(renamed["revision"], verified["revision"] + 1)
        self.assertEqual(renamed["name"], "Renombrado")
        self.assertEqual(renamed["notes"], "Nota sintética")
        self.assertEqual(renamed["physical_result"], "worked")
        self.assertIn("verification", renamed)
        changed = self.code_file("changed.json", marker="BQYHCA==", as_json=True)
        status, stdout, stderr = self.invoke(["save", "--id", record["id"], "--name", "Editado", "--notes", "Nota nueva", "--file", str(changed)])
        self.assertEqual((status, stderr), (0, ""))
        edited = self.library.get(record["id"])
        self.assertEqual(edited["revision"], renamed["revision"] + 1)
        self.assertEqual(edited["notes"], "Nota nueva")
        self.assertEqual(edited["physical_result"], "unverified")
        self.assertNotIn("verification", edited)
        self.assertEqual(len(list(self.directory.glob("*.dpapi"))), 1)
        self.assertNotIn("code", json.loads(stdout))
        self.radio_factory.assert_not_called()

    def test_capture_saves_valid_result_once_and_forwards_parameters(self):
        radio = self.fake_radio()
        radio.capture.return_value = {"code": synthetic_code(), "source_dp": "202", "learning_exit_sent": True,
                                      "physical_verified": False, "origin": "received_during_learning"}
        status, stdout, stderr = self.invoke(["capture", "--name", "Captura sintética", "--frequency", "433.92", "--seconds", "9"])
        self.assertEqual((status, stderr), (0, ""))
        self.radio_factory.assert_called_once_with(self.credentials)
        radio.capture.assert_called_once()
        args, kwargs = radio.capture.call_args
        self.assertIsInstance(args[0], threading.Event)
        self.assertTrue(callable(args[1]))
        self.assertEqual(kwargs, {"frequency": "433.92", "seconds": 9})
        metadata = json.loads(stdout)
        self.assertFalse(metadata["freshness_verified"])
        self.assertNotIn("code", metadata)
        self.assertEqual(self.library.get(metadata["id"])["code"], synthetic_code())
        self.assertEqual(len(list(self.directory.glob("*.dpapi"))), 1)
        radio.send.assert_not_called()

    def test_capture_invalid_result_never_saves(self):
        radio = self.fake_radio()
        radio.capture.return_value = {"code": "invalid-base64", "source_dp": "202", "learning_exit_sent": True}
        status, stdout, stderr = self.invoke(["capture", "--name", "Inválida"])
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assert_no_capture_files()
        radio.capture.assert_called_once()
        radio.send.assert_not_called()

    def test_capture_failure_preserves_exit_warning_and_saves_nothing(self):
        radio = self.fake_radio()
        error = rf_device.RfError("NO_CODE")
        error.cleanup_sent = False
        radio.capture.side_effect = error
        status, stdout, stderr = self.invoke(["capture", "--name", "Sin señal"])
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("salida del aprendizaje", stderr)
        self.assert_no_capture_files()
        radio.capture.assert_called_once()
        radio.send.assert_not_called()

    def test_send_explicit_times_four_sends_once_ack_is_not_physical_verification(self):
        record = self.save_record()
        radio = self.fake_radio()
        radio.send.return_value = self.send_result()
        status, stdout, stderr = self.invoke(["send", record["id"], "--times", "4"])
        self.assertEqual(status, 0)
        result = json.loads(stdout)
        self.assertEqual(result["outcome"], "ACKNOWLEDGED")
        self.assertFalse(result["physical_verified"])
        self.assertTrue(result["history_saved"])
        self.assertIn("no confirma el efecto físico", stderr)
        self.radio_factory.assert_called_once_with(self.credentials)
        radio.send.assert_called_once_with(record["code"], times=4)
        radio.capture.assert_not_called()
        rows = app.TrialLog(self.directory).list()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["times"], 4)
        self.assertEqual(rows[0]["physical_result"], "unverified")
        self.assertEqual(rows[0]["timing_ms"]["total"], 15)
        self.assertNotIn("code", rows[0])
        self.assertEqual(self.library.get(record["id"])["physical_result"], "unverified")

    def test_send_uncertain_never_retries(self):
        record = self.save_record()
        radio = self.fake_radio()
        radio.send.return_value = self.send_result("UNCERTAIN", "TIMEOUT")
        status, stdout, stderr = self.invoke(["send", record["id"], "--times", "4"])
        self.assertEqual(status, 3)
        self.assertEqual(json.loads(stdout)["outcome"], "UNCERTAIN")
        self.assertIn("No hay reintentos automáticos", stderr)
        radio.send.assert_called_once_with(record["code"], times=4)
        self.assertEqual(len(app.TrialLog(self.directory).list()), 1)

    def test_send_journal_failure_does_not_repeat_transmission(self):
        record = self.save_record()
        radio = self.fake_radio()
        radio.send.return_value = self.send_result()
        with patch("l20.app.TrialLog.append", side_effect=OSError("synthetic disk error")) as journal:
            status, stdout, stderr = self.invoke(["send", record["id"], "--times", "4"])
        self.assertEqual(status, 0)
        result = json.loads(stdout)
        self.assertFalse(result["history_saved"])
        self.assertEqual(result["outcome"], "ACKNOWLEDGED")
        radio.send.assert_called_once_with(record["code"], times=4)
        journal.assert_called_once()
        self.assertIn("No hay reintentos automáticos", stderr)
        self.assertNotIn("synthetic disk error", stdout + stderr)

    def test_validate_is_passive_and_omits_code(self):
        source = self.code_file("validate.json", as_json=True)
        with patch("l20.credential_info", side_effect=AssertionError("No se necesita una credencial.")):
            status, stdout, stderr = self.invoke(["validate", "--file", str(source)])
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["version"], "2")
        self.assertNotIn("code", json.loads(stdout))
        self.assert_no_capture_files()
        self.radio_factory.assert_not_called()

    def test_info_is_passive_and_hides_identifiers(self):
        self.credentials.parent.mkdir()
        self.credentials.write_bytes(rf_device.seal(json.dumps(self.synthetic_credentials).encode("utf-8")))
        status, stdout, stderr = self.invoke(["info"])
        self.assertEqual((status, stderr), (0, ""))
        result = json.loads(stdout)
        self.assertTrue(result["ready"])
        self.assertEqual(result["host"], self.synthetic_credentials["target_ip"])
        self.assertNotIn("device_id", result)
        self.assertNotIn("local_key", result)
        for name in ("device_id", "local_key"):
            self.assertNotIn(self.synthetic_credentials[name], stdout + stderr)
        self.radio_factory.assert_not_called()

    def test_info_missing_credential_fails_safely_without_radio(self):
        status, stdout, stderr = self.invoke(["info"])
        self.assertEqual(status, 2)
        self.assertFalse(json.loads(stdout)["ready"])
        self.assertEqual(stderr, "")
        self.radio_factory.assert_not_called()

    def test_web_demo_forwards_flags_and_leaves_data_default_to_server(self):
        with patch("l20.app.main", return_value=0) as web:
            status, stdout, stderr = self.invoke(["web", "--demo", "--no-browser"], with_data=False)
        self.assertEqual((status, stdout, stderr), (0, "", ""))
        web.assert_called_once_with(["--credentials", str(self.credentials), "--port", "58745", "--demo", "--no-browser"])
        self.assertNotIn("--data", web.call_args.args[0])
        self.radio_factory.assert_not_called()

    def test_web_forwards_explicit_data_and_custom_port(self):
        with patch("l20.app.main", return_value=7) as web:
            status, stdout, stderr = self.invoke(["web", "--port", "58999"])
        self.assertEqual((status, stdout, stderr), (7, "", ""))
        web.assert_called_once_with(["--credentials", str(self.credentials), "--port", "58999", "--data", str(self.directory)])
        self.radio_factory.assert_not_called()

    def test_invalid_times_are_rejected_by_parser_before_radio(self):
        for value in ("0", "7", "-1", "invalid"):
            with self.subTest(times=value), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exit_status:
                    l20.main(["send", "00000000-0000-4000-8000-000000000001", "--times", value])
                self.assertEqual(exit_status.exception.code, 2)
        self.radio_factory.assert_not_called()
        self.assert_no_capture_files()


if __name__ == "__main__":
    unittest.main()
