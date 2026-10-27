"""Integración del asistente con datos sintéticos, DPAPI temporal y Cloud falso."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import credential_setup
import credential_store
import l20
import rf_device


@unittest.skipUnless(os.name == "nt", "La persistencia de credenciales usa DPAPI de Windows.")
class SetupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="l20-setup-synthetic-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.destination = self.root / ".private" / "l20.dpapi"
        self.source = self.root / "synthetic-devices.json"
        self.host, self.mac = "10.23.45.67", "02:00:00:23:45:67"
        self.api_id, self.api_secret = "synthetic_api_access_id", "synthetic_api_access_secret"
        self.sample_id = "synthetic_sample_device_id"
        self.devices = [
            {"name": "Receptor sintético uno", "id": "synthetic_device_first_001", "key": "0123456789ABCDEF",
             "apiKey": self.api_id, "apiSecret": self.api_secret},
            {"name": "Receptor sintético dos", "id": "synthetic_device_second_002", "key": "FEDCBA9876543210",
             "apiKey": self.api_id, "apiSecret": self.api_secret},
        ]
        self.secrets = [self.api_id, self.api_secret, self.sample_id]
        self.secrets += [record[key] for record in self.devices for key in ("id", "key")]
        for target in ("rf_device.socket.create_connection", "rf_device.socket.socket", "rf_device._arp_mac"):
            guard = patch(target, side_effect=AssertionError("No se permite red ni ARP en esta prueba."))
            guard.start()
            self.addCleanup(guard.stop)
        radio_guard = patch("l20.Radio", side_effect=AssertionError("El asistente no debe construir Radio."))
        self.radio = radio_guard.start()
        self.addCleanup(radio_guard.stop)
        cloud_guard = patch("credential_setup._cloud_devices", side_effect=AssertionError("No se permite Cloud real."))
        self.cloud = cloud_guard.start()
        self.addCleanup(cloud_guard.stop)

    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = l20.main(["--credentials", str(self.destination), "--data", str(self.root / "capturas"), *arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def write_source(self, value=None):
        self.source.write_text(json.dumps({"devices": self.devices} if value is None else value, ensure_ascii=False), encoding="utf-8")
        return self.source.read_bytes()

    def assert_hidden(self, stdout, stderr):
        for secret in self.secrets:
            self.assertNotIn(secret, stdout + stderr)

    def assert_only_selected_credential(self, selected=1, *, source_present=True):
        paths = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file())
        expected = [".private/l20.dpapi"] + ([self.source.name] if source_present else [])
        self.assertEqual(paths, sorted(expected))
        ciphertext = self.destination.read_bytes()
        payload = json.loads(rf_device.unseal(ciphertext))
        self.assertEqual(set(payload), {"target_ip", "target_mac", "device_id", "local_key", "port", "version"})
        self.assertEqual(payload, {"target_ip": self.host, "target_mac": self.mac,
                                  "device_id": self.devices[selected]["id"], "local_key": self.devices[selected]["key"],
                                  "port": 6668, "version": "3.3"})
        loaded = rf_device.load_credentials(self.destination)
        self.assertEqual(loaded.target_ip, self.host)
        self.assertEqual(loaded.target_mac, self.mac)
        self.assertEqual(loaded.device_id, self.devices[selected]["id"])
        self.assertEqual(loaded.local_key, self.devices[selected]["key"].encode("ascii"))
        for secret in self.secrets:
            self.assertNotIn(secret.encode("ascii"), ciphertext)
        self.radio.assert_not_called()

    def test_cli_routes_setup_flags_without_running_another_command(self):
        with patch("l20.run_setup") as setup, patch("l20.configure") as configure:
            status, stdout, stderr = self.invoke(["setup", "--from-file", str(self.source), "--replace"])
        self.assertEqual((status, stdout, stderr), (0, "", ""))
        setup.assert_called_once_with(self.destination, from_file=self.source, replace=True, demo=False)
        configure.assert_not_called()
        self.cloud.assert_not_called()
        self.radio.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_setup_defaults_do_not_enable_replacement_or_demo(self):
        with patch("l20.run_setup") as setup:
            status, stdout, stderr = self.invoke(["setup"])
        self.assertEqual((status, stdout, stderr), (0, "", ""))
        setup.assert_called_once_with(self.destination, from_file=None, replace=False, demo=False)

    def test_setup_demo_uses_no_cloud_no_credential_file_and_no_persistence(self):
        with patch("builtins.input", side_effect=["1", "2", self.host, self.mac, "s"]), \
                patch("credential_setup.write_credentials", side_effect=AssertionError("Demo no puede persistir.")) as writer, \
                patch("rf_device.load_credentials", side_effect=AssertionError("Demo no debe leer credenciales.")):
            status, stdout, stderr = self.invoke(["setup", "--demo"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(list(self.root.iterdir()), [])
        self.cloud.assert_not_called()
        self.radio.assert_not_called()
        writer.assert_not_called()
        self.assert_hidden(stdout, stderr)

    def test_import_selects_second_device_and_saves_one_minimal_dpapi_record(self):
        original = self.write_source()
        with patch("builtins.input", side_effect=["2", self.host, self.mac.lower(), "s"]), \
                patch("credential_setup.write_credentials", wraps=credential_store.write_credentials) as writer:
            status, stdout, stderr = self.invoke(["setup", "--from-file", str(self.source)])
        self.assertEqual(status, 0, stderr)
        writer.assert_called_once()
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_only_selected_credential()
        self.assert_hidden(stdout, stderr)
        self.cloud.assert_not_called()

    def test_demo_from_file_is_rejected_before_path_access_prompts_cloud_or_writes(self):
        with patch("builtins.input") as prompts, \
                patch("credential_setup.Path.stat", side_effect=AssertionError("No debe consultar rutas.")) as stat, \
                patch("credential_setup.Path.open", side_effect=AssertionError("No debe abrir archivos.")) as opened, \
                patch("credential_setup.check_destination", side_effect=AssertionError("No debe consultar el destino.")) as destination_check, \
                patch("credential_setup._read_file", side_effect=AssertionError("No debe leer fuentes.")) as reader, \
                patch("credential_setup.write_credentials", side_effect=AssertionError("No debe persistir.")) as writer:
            status, stdout, stderr = self.invoke(["setup", "--demo", "--from-file", str(self.source)])
        self.assertEqual(status, 2)
        self.assertIn("--demo", stderr)
        self.assertIn("--from-file", stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(list(self.root.iterdir()), [])
        for boundary in (prompts, stat, opened, destination_check, reader, writer, self.cloud, self.radio):
            boundary.assert_not_called()
        self.assert_hidden(stdout, stderr)

    def test_demo_without_from_file_ignores_existing_credential_without_path_access(self):
        self.destination.parent.mkdir()
        self.destination.write_bytes(b"synthetic preexisting credential")
        before = self.destination.read_bytes()
        with patch("builtins.input", side_effect=["1", "2", "", "", "s"]), \
                patch("credential_setup.Path.stat", side_effect=AssertionError("Demo no debe consultar rutas.")) as stat, \
                patch("credential_setup.Path.open", side_effect=AssertionError("Demo no debe abrir archivos.")) as opened, \
                patch("credential_setup.check_destination", side_effect=AssertionError("Demo no debe consultar el destino.")) as destination_check, \
                patch("credential_setup._read_file", side_effect=AssertionError("Demo no debe leer fuentes.")) as reader, \
                patch("credential_setup.write_credentials", side_effect=AssertionError("Demo no puede persistir.")) as writer, \
                patch("rf_device.load_credentials", side_effect=AssertionError("Demo no debe leer credenciales.")):
            status, stdout, stderr = self.invoke(["setup", "--demo"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(self.destination.read_bytes(), before)
        self.assertEqual(len([path for path in self.root.rglob("*") if path.is_file()]), 1)
        for boundary in (stat, opened, destination_check, reader, writer, self.cloud, self.radio):
            boundary.assert_not_called()
        self.assert_hidden(stdout, stderr)
        self.assertNotIn("demo_l20_device_002", stdout + stderr)
        self.assertNotIn("fedcba9876543210", stdout + stderr)

    def test_declining_confirmation_preserves_source_and_saves_nothing(self):
        original = self.write_source()
        with patch("builtins.input", side_effect=["2", self.host, self.mac, "n"]), \
                patch("credential_setup.write_credentials", wraps=credential_store.write_credentials) as writer:
            status, stdout, stderr = self.invoke(["setup", "--from-file", str(self.source)])
        self.assertEqual(status, 0, stderr)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), original)
        writer.assert_not_called()
        self.cloud.assert_not_called()
        self.radio.assert_not_called()
        self.assert_hidden(stdout, stderr)

    def test_existing_destination_is_rejected_before_prompts_or_cloud(self):
        self.destination.parent.mkdir()
        self.destination.write_bytes(b"synthetic existing encrypted file")
        with patch("builtins.input") as prompts, patch("credential_setup.getpass.getpass") as hidden:
            status, stdout, stderr = self.invoke(["setup"])
        self.assertEqual(status, 2)
        self.assertIn("--replace", stderr)
        self.assertEqual(self.destination.read_bytes(), b"synthetic existing encrypted file")
        prompts.assert_not_called()
        hidden.assert_not_called()
        self.cloud.assert_not_called()
        self.assert_hidden(stdout, stderr)

    def test_replace_refuses_source_equal_to_destination_before_import_or_write(self):
        self.destination.parent.mkdir()
        original = json.dumps({"devices": self.devices}, ensure_ascii=False).encode("utf-8")
        self.destination.write_bytes(original)
        with patch("builtins.input") as prompts, \
                patch("credential_setup._read_file", side_effect=AssertionError("No debe importar el destino.")) as reader, \
                patch("credential_setup.write_credentials", side_effect=AssertionError("No debe sobrescribir la fuente.")) as writer:
            status, stdout, stderr = self.invoke(["setup", "--replace", "--from-file", str(self.destination)])
        self.assertEqual(status, 2)
        self.assertTrue(stderr.strip())
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual([path for path in self.root.rglob("*") if path.is_file()], [self.destination])
        for boundary in (prompts, reader, writer, self.cloud, self.radio):
            boundary.assert_not_called()
        self.assert_hidden(stdout, stderr)

    def test_menu_import_refuses_source_equal_to_destination_with_replace(self):
        self.destination.parent.mkdir()
        original = json.dumps({"devices": self.devices}, ensure_ascii=False).encode("utf-8")
        self.destination.write_bytes(original)
        with patch("builtins.input", side_effect=["2", str(self.destination)]) as prompts, \
                patch("credential_setup._read_file", side_effect=AssertionError("No debe importar el destino.")) as reader, \
                patch("credential_setup.write_credentials", side_effect=AssertionError("No debe sobrescribir la fuente.")) as writer:
            status, stdout, stderr = self.invoke(["setup", "--replace"])
        self.assertEqual(status, 2)
        self.assertTrue(stderr.strip())
        self.assertEqual(prompts.call_count, 2)
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual([path for path in self.root.rglob("*") if path.is_file()], [self.destination])
        for boundary in (reader, writer, self.cloud, self.radio):
            boundary.assert_not_called()
        self.assert_hidden(stdout, stderr)

    def test_replace_refuses_hardlink_alias_of_import_source(self):
        original = self.write_source()
        self.destination.parent.mkdir()
        try:
            os.link(self.source, self.destination)
        except OSError:
            self.skipTest("Este sistema no permite hardlinks temporales para la prueba.")
        self.assertTrue(os.path.samefile(self.source, self.destination))
        with patch("builtins.input") as prompts, \
                patch("credential_setup._read_file", side_effect=AssertionError("No debe importar un alias del destino.")) as reader, \
                patch("credential_setup.write_credentials", side_effect=AssertionError("No debe sobrescribir la fuente.")) as writer:
            status, stdout, stderr = self.invoke(["setup", "--replace", "--from-file", str(self.source)])
        self.assertEqual(status, 2)
        self.assertTrue(stderr.strip())
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertTrue(os.path.samefile(self.source, self.destination))
        self.assertEqual(len([path for path in self.root.rglob("*") if path.is_file()]), 2)
        for boundary in (prompts, reader, writer, self.cloud, self.radio):
            boundary.assert_not_called()
        self.assert_hidden(stdout, stderr)

    def test_invalid_json_is_preserved_and_creates_no_destination(self):
        self.source.write_text('{"devices": [not valid JSON', encoding="utf-8")
        original = self.source.read_bytes()
        with patch("builtins.input") as prompts:
            status, stdout, stderr = self.invoke(["setup", "--from-file", str(self.source)])
        self.assertEqual(status, 2)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), original)
        prompts.assert_not_called()
        self.cloud.assert_not_called()
        self.assert_hidden(stdout, stderr)

    def test_invalid_multi_record_selection_does_not_choose_another_device(self):
        original = self.write_source()
        with patch("builtins.input", side_effect=["99"]):
            status, stdout, stderr = self.invoke(["setup", "--from-file", str(self.source)])
        self.assertEqual(status, 2)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_hidden(stdout, stderr)
        self.cloud.assert_not_called()

    def test_selected_record_with_invalid_key_is_not_written(self):
        invalid = [dict(self.devices[0]), dict(self.devices[1], key="invalid-key")]
        original = self.write_source({"devices": invalid})
        with patch("builtins.input", side_effect=["2", self.host, self.mac, "s"]):
            status, stdout, stderr = self.invoke(["setup", "--from-file", str(self.source)])
        self.assertEqual(status, 2)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_hidden(stdout, stderr)
        self.cloud.assert_not_called()

    def test_import_requires_private_lan_destination_before_saving(self):
        original = self.write_source()
        with patch("builtins.input", side_effect=["2", "127.0.0.1", self.mac, "s"]):
            status, stdout, stderr = self.invoke(["setup", "--from-file", str(self.source)])
        self.assertEqual(status, 2)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_hidden(stdout, stderr)

    def test_fake_cloud_uses_one_selected_device_without_cloud_credential_files(self):
        self.cloud.side_effect = None
        self.cloud.return_value = self.devices
        with patch("builtins.input", side_effect=["1", "eu", "2", self.host, self.mac, "s"]), \
                patch("credential_setup.getpass.getpass", side_effect=[self.api_id, self.api_secret, self.sample_id]), \
                patch("credential_setup.write_credentials", wraps=credential_store.write_credentials) as writer:
            status, stdout, stderr = self.invoke(["setup"])
        self.assertEqual(status, 0, stderr)
        self.cloud.assert_called_once_with("eu", self.api_id, self.api_secret, self.sample_id)
        writer.assert_called_once()
        self.assert_only_selected_credential(source_present=False)
        self.assert_hidden(stdout, stderr)

    def test_manual_configure_keeps_previous_prompt_and_dpapi_semantics(self):
        with patch("builtins.input", side_effect=[self.host, self.mac.lower()]) as visible, \
                patch("l20.getpass.getpass", side_effect=[self.devices[0]["id"], self.devices[0]["key"]]) as hidden, \
                patch("l20.write_credentials", wraps=credential_store.write_credentials) as writer, \
                patch("l20.run_setup") as setup:
            status, stdout, stderr = self.invoke(["configure"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(visible.call_count, 2)
        self.assertEqual(hidden.call_count, 2)
        writer.assert_called_once()
        setup.assert_not_called()
        self.cloud.assert_not_called()
        self.assert_only_selected_credential(selected=0, source_present=False)
        self.assert_hidden(stdout, stderr)


if __name__ == "__main__":
    unittest.main()
