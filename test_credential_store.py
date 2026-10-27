"""DPAPI storage with synthetic credentials; no network or real configuration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from credential_store import CredentialStoreError, write_credentials
from rf_device import RfError, load_credentials, unseal


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "private-test"
        self.destination = self.directory / "l20.dpapi"
        self.value = {"target_ip": "10.44.55.66", "target_mac": "02:11:22:AA:BB:CC",
                      "device_id": "synthetic-store-device", "local_key": "0123456789abcdef"}

    def test_only_selected_lan_fields_are_persisted_encrypted(self):
        value = {**self.value, "apiKey": "CLOUD_ONLY_TEST_VALUE", "apiSecret": "OTHER_CLOUD_TEST_VALUE",
                 "access_token": "TOKEN_ONLY_TEST_VALUE", "name": "Nombre de prueba"}
        write_credentials(self.destination, value)
        ciphertext = self.destination.read_bytes()
        for secret in (value["local_key"], value["device_id"], value["apiKey"], value["apiSecret"]):
            self.assertNotIn(secret.encode(), ciphertext)
        stored = json.loads(unseal(ciphertext))
        self.assertEqual(set(stored), {"target_ip", "target_mac", "device_id", "local_key", "port", "version"})
        self.assertEqual(load_credentials(self.destination).local_key, self.value["local_key"].encode())
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ["l20.dpapi"])

    def test_existing_destination_is_not_encrypted_or_overwritten_without_replace(self):
        write_credentials(self.destination, self.value)
        original = self.destination.read_bytes()
        with patch("credential_store.seal") as protect:
            with self.assertRaises(CredentialStoreError):
                write_credentials(self.destination, self.value)
        protect.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), original)

    def test_invalid_profile_creates_no_directory(self):
        with self.assertRaises(RfError):
            write_credentials(self.destination, {**self.value, "version": "3.4"})
        self.assertFalse(self.directory.exists())

    def test_failed_atomic_replace_preserves_original_and_removes_temporary(self):
        write_credentials(self.destination, self.value)
        original = self.destination.read_bytes()
        with patch("credential_store.os.replace", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                write_credentials(self.destination, {**self.value, "device_id": "synthetic-new-device"}, replace=True)
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ["l20.dpapi"])

    def test_explicit_replace_loads_new_record(self):
        write_credentials(self.destination, self.value)
        write_credentials(self.destination, {**self.value, "device_id": "synthetic-new-device"}, replace=True)
        self.assertEqual(load_credentials(self.destination).device_id, "synthetic-new-device")


if __name__ == "__main__":
    unittest.main()
