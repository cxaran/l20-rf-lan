"""Pruebas de persistencia, exclusión mutua y HTTP. Sin dispositivo ni RF."""
import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from app import AppError, Application, Handler, Library, Server


def sample(marker="AQIDBA=="):
    return base64.b64encode(json.dumps({"num": 1, "ver": "2", "study_feq": "433.92", "data0": marker, "lv": [0]}).encode()).decode()


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = Library(Path(self.temp.name) / "capturas")

    def test_encrypted_save_reload_revision_and_changed_code_reset(self):
        record = self.library.save({"name": "Mando uno", "notes": "Botón izquierdo", "code": sample()})
        ciphertext = next(self.library.directory.glob("*.dpapi")).read_bytes()
        self.assertNotIn(sample().encode(), ciphertext)
        self.assertNotIn(b"Mando uno", ciphertext)
        self.assertEqual(Library(self.library.directory).get(record["id"]), record)
        from app import code_hash
        verified = self.library.verify(record["id"], 1, code_hash(record["code"]), True)
        self.assertEqual(verified["physical_result"], "worked")
        renamed = self.library.save(dict(verified, name="Otro nombre"))
        self.assertEqual(renamed["physical_result"], "worked")
        edited = self.library.save(dict(renamed, code=sample("BQYHCA==")))
        self.assertEqual(edited["physical_result"], "unverified")
        self.assertNotIn("verification", edited)
        self.assertEqual(edited["revision"], 4)
        with self.assertRaises(AppError):
            self.library.save(dict(renamed, name="Revisión desactualizada"))

    def test_metadata_omits_codes_and_paths_are_fixed(self):
        record = self.library.save({"name": "<script>nombre</script>", "code": sample()})
        records, unreadable = self.library.list()
        self.assertEqual(unreadable, 0)
        self.assertNotIn("code", records[0])
        self.assertEqual(records[0]["name"], record["name"])
        with self.assertRaises(AppError):
            self.library.get("../../credentials")
        with self.assertRaises(AppError):
            self.library.verify(record["id"], 1, "different", True)

    def test_unreadable_file_preserved_and_reported(self):
        self.library.directory.mkdir()
        path = self.library.directory / (str(uuid.uuid4()) + ".dpapi")
        path.write_bytes(b"not a DPAPI capture")
        self.assertEqual(self.library.list(), ([], 1))
        self.assertEqual(path.read_bytes(), b"not a DPAPI capture")


class BlockingRadio:
    def __init__(self):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def send(self, code, times=1, progress=None):
        self.calls += 1
        self.started.set()
        self.release.wait(3)
        return {"outcome": "ACKNOWLEDGED", "problem": "NONE", "frame_write_attempted": True, "physical_verified": False}


class OperationTests(unittest.TestCase):
    def test_trial_journal_records_once_and_physical_observation_never_sends(self):
        class MeasuredRadio:
            calls = 0
            def send(self, code, times=1, progress=None):
                self.calls += 1
                return {"outcome": "ACKNOWLEDGED", "problem": "NONE", "frame_write_attempted": True,
                        "physical_verified": False, "times": times, "timing_ms": {"total": 12.5}}
        with tempfile.TemporaryDirectory() as directory:
            radio = MeasuredRadio()
            with patch("app.credential_info", return_value={"ready": True}):
                app = Application("unused", directory, radio=radio)
            request = {"request_id": str(uuid.uuid4()), "code": sample(), "times": 3, "name": "Control sintético"}
            operation = app.test(request)
            app.worker.join(2)
            app.test(request)
            rows = app.trials.list()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["times"], 3)
            self.assertEqual(rows[0]["timing_ms"]["total"], 12.5)
            self.assertEqual(rows[0]["physical_result"], "unverified")
            self.assertNotIn("code", rows[0])
            self.assertNotIn(sample().encode(), app.trials.path.read_bytes())
            observed = app.observe_trial({"operation_id": operation["id"], "worked": False})
            self.assertEqual(observed["physical_result"], "failed")
            self.assertEqual(observed["reported_by"], "user")
            self.assertEqual(radio.calls, 1)
            self.assertEqual(type(app.trials)(directory).list()[0]["physical_result"], "failed")

    def test_trial_disk_failure_cannot_retry_finished_send(self):
        radio = BlockingRadio()
        radio.release.set()
        with tempfile.TemporaryDirectory() as directory:
            app = Application("unused", directory, demo=True, radio=radio)
            request = {"request_id": str(uuid.uuid4()), "code": sample(), "times": 1}
            with patch.object(app.trials, "append", side_effect=OSError("synthetic disk failure")):
                operation = app.test(request)
                app.worker.join(2)
            result = app.operation_state()["result"]
            self.assertEqual(result["outcome"], "ACKNOWLEDGED")
            self.assertFalse(result["history_saved"])
            self.assertEqual(app.test(request)["id"], operation["id"])
            self.assertEqual(radio.calls, 1)

    def test_capture_error_preserves_safe_problem_and_exit_warning(self):
        from rf_device import RfError
        class FailedCapture:
            def capture(self, *args, **kwargs):
                error = RfError("KEY_OR_VERSION")
                error.cleanup_sent = False
                raise error
        with tempfile.TemporaryDirectory() as directory:
            app = Application("unused", directory, demo=True, radio=FailedCapture())
            app.capture({"frequency": "0"})
            app.worker.join(2)
            operation = app.state()["operation"]
            self.assertEqual(operation["phase"], "error")
            self.assertEqual(operation["problem"], "KEY_OR_VERSION")
            self.assertFalse(operation["learning_exit_sent"])
            self.assertIn("salida del aprendizaje", operation["message"])
            self.assertNotIn("result", operation)

    def test_duplicate_manual_request_never_retransmits_and_busy_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            radio = BlockingRadio()
            app = Application("unused", directory, demo=True, radio=radio)
            self.addCleanup(app.close)
            request = {"request_id": str(uuid.uuid4()), "code": sample(), "times": 1}
            first = app.test(request)
            self.assertTrue(radio.started.wait(1))
            duplicate = app.test(request)
            self.assertEqual(first["id"], duplicate["id"])
            with self.assertRaises(AppError):
                app.capture({"frequency": "0"})
            with self.assertRaises(AppError):
                app.test(dict(request, request_id=str(uuid.uuid4())))
            radio.release.set()
            app.worker.join(2)
            self.assertEqual(app.test(request)["id"], first["id"])
            self.assertEqual(radio.calls, 1)
            self.assertFalse(app.state()["operation"]["result"]["physical_verified"])

    def test_verification_requires_exact_saved_code_and_real_write(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application("unused", directory, demo=True)
            saved = app.library.save({"name": "Mando", "code": sample()})
            request = {"request_id": str(uuid.uuid4()), "code": sample()}
            operation = app.test(request)
            app.worker.join(2)
            data = {"capture_id": saved["id"], "revision": 1, "operation_id": operation["id"], "worked": True}
            with self.assertRaises(AppError):
                app.verify(data)
            app.demo = False
            app.operation["result"]["frame_write_attempted"] = True
            result = app.verify(data)
            self.assertEqual(result["physical_result"], "worked")
            self.assertEqual(result["verification"]["reported_by"], "user")
            self.assertEqual(result["revision"], 2)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.radio = BlockingRadio()
        self.app = Application("unused", self.temp.name, demo=True, radio=self.radio)
        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.radio.release.set()
        self.app.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        actual = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, json.dumps(data) if data is not None else None, headers=actual)
        response = connection.getresponse()
        body = response.read()
        result = (response.status, body, response.getheaders())
        connection.close()
        return result

    def test_gets_are_passive_and_cross_origin_posts_blocked(self):
        self.assertEqual(self.request("GET", "/api/state")[0], 200)
        self.assertEqual(self.request("GET", "/api/session")[0], 200)
        payload = {"request_id": str(uuid.uuid4()), "code": sample(), "times": 1}
        self.assertEqual(self.request("POST", "/api/test", payload)[0], 403)
        headers = {"X-CSRF-Token": self.app.csrf, "Origin": "http://malicious.example"}
        self.assertEqual(self.request("POST", "/api/test", payload, headers)[0], 403)
        self.assertEqual(self.request("GET", "/api/session", headers={"Host": "other.example"})[0], 403)
        self.assertEqual(self.radio.calls, 0)
        headers = {"X-CSRF-Token": self.app.csrf}
        self.assertEqual(self.request("POST", "/api/test", payload, headers)[0], 202)
        self.assertTrue(self.radio.started.wait(1))
        self.assertEqual(self.radio.calls, 1)

    def test_operation_endpoint_avoids_library_and_history_reads(self):
        with patch.object(self.app.library, "list", side_effect=AssertionError("must remain lightweight")), patch.object(self.app.trials, "list", side_effect=AssertionError("no history reads")):
            status, body, _ = self.request("GET", "/api/operation")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"operation": None})
        self.assertEqual(self.radio.calls, 0)

    def test_invalid_json_validation_and_save_api(self):
        headers = {"X-CSRF-Token": self.app.csrf}
        self.assertEqual(self.request("POST", "/api/validate", {"code": "bad"}, headers)[0], 400)
        status, body, response_headers = self.request("POST", "/api/captures", {"name": "Prueba API", "code": sample()}, headers)
        self.assertEqual(status, 200)
        record = json.loads(body)["record"]
        status, body, _ = self.request("GET", "/api/captures/" + record["id"])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["record"]["code"], sample())
        self.assertIn(("Cache-Control", "no-store"), response_headers)
        status, body, _ = self.request("GET", "/api/state")
        self.assertNotIn(sample().encode(), body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
