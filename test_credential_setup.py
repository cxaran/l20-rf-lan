"""Credential parser and isolated Cloud worker tests; no real accounts/network."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import warnings

import credential_setup as setup


def device(**changes):
    value = {"id": "synthetic_device_001", "key": "0123456789abcdef",
             "name": "L20 de prueba", "mac": "02-00-00-23-45-67"}
    value.update(changes)
    return value


def query():
    return {"region": "eu", "api_id": "synthetic_api_access_001",
        "api_secret": "ZZsyntheticSecretForTest001", "sample_device_id": "reference_device_001"}


class CredentialSetupTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(setup.subprocess, "run", side_effect=AssertionError("No real Cloud calls"))
        self.process_guard = guard.start()
        self.addCleanup(guard.stop)
        socket_guard = patch("rf_device.socket.socket", side_effect=AssertionError("No LAN/RF"))
        socket_guard.start()
        self.addCleanup(socket_guard.stop)

    def test_json_accepts_bom_and_rejects_duplicates_nesting_nan_and_size(self):
        self.assertEqual(setup._strict_json(b'\xef\xbb\xbf{"devices":[]}'), {"devices": []})
        bad = [b'{"devices":[],"devices":[]}', b'{"nested":{"x":1,"x":2}}',
               b'{"number":NaN}', b'[' * 17 + b'0' + b']' * 17, b'\xff', b'',
               b' ' * (setup.MAX_JSON + 1)]
        for value in bad:
            with self.subTest(size=len(value)):
                with self.assertRaises(setup.SetupError):
                    setup._strict_json(value)

    def test_record_aliases_duplicate_ids_and_ambiguous_keys(self):
        records = setup._records({"devices": [device(device_id="synthetic_device_001",
                                                    local_key="0123456789abcdef")]})
        self.assertEqual(records[0].device_id, "synthetic_device_001")
        self.assertNotIn("0123456789abcdef", repr(records[0]))
        bad = [[device(), device()], [device(device_id="different_device")],
               [device(local_key="fedcba9876543210")], [None], {}, [device(id="bad id")]]
        for value in bad:
            with self.assertRaises(setup.SetupError):
                setup._records(value)

    def test_names_are_terminal_safe_and_redacted_before_truncation(self):
        secret = "ZZsyntheticSecretForTest001"
        row = device(name="\x1b[31m" + "x" * 70 + secret + " synthetic_device_001", apiSecret=secret)
        records = setup._records([row])
        output = io.StringIO()
        with patch("builtins.input", return_value="1"), redirect_stdout(output):
            setup._choose(records)
        self.assertNotIn("\x1b", output.getvalue())
        self.assertNotIn(secret, output.getvalue())
        self.assertNotIn(secret[:8], output.getvalue())
        self.assertNotIn(row["id"], output.getvalue())
        self.assertNotIn(row["key"], output.getvalue())
        self.assertIn("syn••••001", output.getvalue())

    def test_hidden_input_fails_instead_of_echo_fallback(self):
        def fallback(_):
            warnings.warn("synthetic warning detail", setup.getpass.GetPassWarning)
            return "must never return"
        with patch.object(setup.getpass, "getpass", side_effect=fallback):
            with self.assertRaises(setup.SetupError) as caught:
                setup._hidden("Secret: ")
        self.assertNotIn("warning detail", str(caught.exception))

    def test_invalid_region_is_rejected_before_subprocess(self):
        for region in ("az", "ue", "invalid", "https://example.com"):
            with self.assertRaises(setup.SetupError):
                setup._cloud_devices(region, "api", "secret", "device")
        self.process_guard.assert_not_called()

    def test_cloud_transport_uses_private_stdin_and_hard_deadline(self):
        request = query()
        response = json.dumps({"ok": True, "devices": [device()]}).encode()
        process_result = SimpleNamespace(returncode=0, stdout=response, stderr=b"ignored synthetic SDK details")
        output = io.StringIO()
        with patch.object(setup.subprocess, "run", return_value=process_result) as run, redirect_stdout(output):
            records = setup._cloud_devices(**request)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], sys.executable)
        self.assertEqual(args[0][1], "-B")
        self.assertEqual(args[0][-1], "--cloud-worker")
        for secret in request.values():
            self.assertNotIn(secret, repr(args))
        self.assertEqual(json.loads(kwargs["input"]), request)
        self.assertEqual(kwargs["timeout"], 20)
        self.assertNotIn("env", kwargs)
        self.assertFalse(kwargs["check"])
        self.assertEqual(records[0]["id"], device()["id"])
        self.assertEqual(output.getvalue(), "")

    def test_cloud_timeout_and_failures_never_expose_sdk_output(self):
        secret = query()["api_secret"]
        failures = [subprocess.TimeoutExpired("worker", 20, output=secret.encode()),
            SimpleNamespace(returncode=1, stdout=secret.encode(), stderr=secret.encode()),
            SimpleNamespace(returncode=0, stdout=b'{"ok":false}', stderr=secret.encode()),
            SimpleNamespace(returncode=0, stdout=b'{"ok":true,"devices":[]}', stderr=b'')]
        for failure in failures:
            options = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
            with patch.object(setup.subprocess, "run", **options):
                with self.assertRaises(setup.SetupError) as caught:
                    setup._cloud_devices(**query())
            self.assertNotIn(secret, str(caught.exception))

    def test_sdk_parameters_explicit_and_no_logs_or_api_credentials_in_names(self):
        credentials = query()
        row = device(name="x" * 70 + credentials["api_secret"])
        cloud = SimpleNamespace(error=None, token="synthetic_token",
            getdevices=Mock(return_value=[row]), apiKey="clear me", apiSecret="clear me",
            apiDeviceID="clear me", getdevices_raw={"private": "raw"})
        def factory(**kwargs):
            print(credentials["api_secret"])
            print(credentials["api_id"], file=sys.stderr)
            logging.critical(credentials["api_secret"])
            return cloud
        constructor = Mock(side_effect=factory)
        module = SimpleNamespace(Cloud=constructor)
        stdout, stderr = io.StringIO(), io.StringIO()
        original_logging = logging.root.manager.disable
        with patch.dict(sys.modules, {"tinytuya": module}), redirect_stdout(stdout), redirect_stderr(stderr):
            records = setup._fetch_cloud(credentials)
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        constructor.assert_called_once_with(apiRegion="eu", apiKey=credentials["api_id"],
            apiSecret=credentials["api_secret"], apiDeviceID=credentials["sample_device_id"],
            new_sign_algorithm=True, initial_token=None, configFile="")
        cloud.getdevices.assert_called_once_with(verbose=False, include_map=False)
        self.assertNotIn(credentials["api_secret"][:8], records[0]["name"])
        self.assertEqual(set(records[0]), {"name", "device_id", "local_key", "mac", "port", "version"})
        self.assertIsNone(cloud.token)
        self.assertIsNone(cloud.apiSecret)
        self.assertEqual(logging.root.manager.disable, original_logging)

    def test_sdk_auth_failure_never_lists_devices(self):
        cloud = SimpleNamespace(error={"Payload": "synthetic sensitive SDK error"},
                                getdevices=Mock(), token=None)
        with patch.dict(sys.modules, {"tinytuya": SimpleNamespace(Cloud=Mock(return_value=cloud))}):
            with self.assertRaises(setup.SetupError) as caught:
                setup._fetch_cloud(query())
        cloud.getdevices.assert_not_called()
        self.assertNotIn("sensitive SDK", str(caught.exception))

    def test_worker_failure_returns_only_fixed_json(self):
        output = SimpleNamespace(buffer=io.BytesIO())
        source = SimpleNamespace(buffer=io.BytesIO(json.dumps(query()).encode()))
        with patch.object(sys, "stdin", source), patch.object(sys, "stdout", output), \
                patch.object(setup, "_fetch_cloud", side_effect=RuntimeError("synthetic secret")):
            setup._cloud_worker()
        self.assertEqual(output.buffer.getvalue(), b'{"ok":false}')

    def test_file_with_embedded_nul_is_safe_error(self):
        with self.assertRaises(setup.SetupError) as caught:
            setup._read_file("synthetic\x00name")
        self.assertNotIn("embedded", str(caught.exception))
        self.assertNotIn("synthetic", str(caught.exception))

    def test_demo_and_file_combination_fails_before_any_io_or_prompt(self):
        with patch("builtins.input") as prompt, patch.object(setup, "check_destination") as check, \
                patch.object(setup, "_read_file") as read, patch.object(setup, "seal") as seal:
            with self.assertRaises(setup.SetupError):
                setup.run_setup("unused", from_file="unused", demo=True)
        prompt.assert_not_called()
        check.assert_not_called()
        read.assert_not_called()
        seal.assert_not_called()

    def test_demo_confirms_and_seals_in_ram_without_destination_or_cloud(self):
        stdout = io.StringIO()
        with patch("builtins.input", side_effect=["1", "2", "", "", "s"]), \
                patch.object(setup, "check_destination") as check, patch.object(setup, "write_credentials") as write, \
                patch.object(setup, "_cloud_devices") as cloud, patch.object(setup, "seal", return_value=b"synthetic") as seal, \
                redirect_stdout(stdout):
            setup.run_setup("unused", demo=True)
        check.assert_not_called()
        write.assert_not_called()
        cloud.assert_not_called()
        seal.assert_called_once()
        self.assertIn("sin crear ni sustituir", stdout.getvalue())
        self.assertNotIn("fedcba9876543210", stdout.getvalue())

    def test_selected_unsupported_version_fails_without_forcing_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.json"
            source.write_text(json.dumps([device(version="3.4"), device(id="other_device", version="3.3")]))
            with patch("builtins.input", side_effect=["1"]) as prompts, \
                    patch.object(setup, "check_destination"), patch.object(setup, "write_credentials") as write, \
                    redirect_stdout(io.StringIO()):
                with self.assertRaises(setup.SetupError):
                    setup.run_setup(Path(directory) / "output.dpapi", from_file=source)
            self.assertEqual(prompts.call_count, 1)
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
