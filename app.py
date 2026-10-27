"""L20 RF LAN: interfaz local. Abrir la página no contacta con el L20."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import uuid
import webbrowser

from rf_device import Radio, RfError, credential_info, seal, unseal, validate_code

ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIAL = ROOT / ".private" / "l20.dpapi"
MAX_BODY = 100_000


class AppError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def code_hash(code):
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def checked_id(value):
    if not isinstance(value, str):
        raise AppError("Identificador inválido.")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except ValueError:
        raise AppError("Identificador inválido.") from None
    return value


class Library:
    """Un registro DPAPI por captura, con reemplazo atómico y revisión."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.RLock()

    def _path(self, capture_id):
        return self.directory / (checked_id(capture_id) + ".dpapi")

    def _read(self, capture_id):
        try:
            path = self._path(capture_id)
            if path.is_symlink():
                raise AppError("Archivo de captura no admitido.")
            value = json.loads(unseal(path.read_bytes()))
            if value.get("id") != capture_id:
                raise ValueError()
            return value
        except FileNotFoundError:
            raise AppError("No se encontró la captura.", 404) from None
        except (OSError, ValueError, RfError):
            raise AppError("Windows no pudo leer esta captura cifrada.") from None

    def get(self, capture_id):
        with self.lock:
            return self._read(capture_id)

    def _write(self, record):
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise AppError("Carpeta de capturas no admitida.")
        path = self._path(record["id"])
        temporary = self.directory / ("." + secrets.token_hex(16) + ".tmp")
        encrypted = seal(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        try:
            with temporary.open("xb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self):
        records = []
        unreadable = 0
        with self.lock:
            for path in self.directory.glob("*.dpapi"):
                try:
                    record = self._read(path.stem)
                    records.append({k: v for k, v in record.items() if k != "code"})
                except AppError:
                    unreadable += 1
        records.sort(key=lambda item: item["updated_at"], reverse=True)
        return records, unreadable

    def save(self, data):
        name, notes = data.get("name", ""), data.get("notes", "")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise AppError("Escribe un nombre de hasta 100 caracteres.")
        if not isinstance(notes, str) or len(notes) > 2000:
            raise AppError("Las notas admiten hasta 2000 caracteres.")
        checked = validate_code(data.get("code"))
        with self.lock:
            previous = None
            if data.get("id"):
                previous = self._read(data["id"])
                if type(data.get("revision")) is not int or data["revision"] != previous["revision"]:
                    raise AppError("La captura cambió en otra ventana. Vuelve a seleccionarla.", 409)
            record = {
                "id": previous["id"] if previous else str(uuid.uuid4()),
                "name": name.strip(), "notes": notes,
                "code": checked["canonical_code"], "summary": checked["summary"],
                "revision": previous["revision"] + 1 if previous else 1,
                "created_at": previous["created_at"] if previous else now(),
                "updated_at": now(), "physical_result": "unverified",
            }
            if previous and previous["code"] == record["code"]:
                record["physical_result"] = previous.get("physical_result", "unverified")
                if "verification" in previous:
                    record["verification"] = previous["verification"]
            self._write(record)
            return record

    def verify(self, capture_id, revision, digest, worked):
        with self.lock:
            record = self._read(capture_id)
            if type(revision) is not int or record["revision"] != revision:
                raise AppError("Guarda o vuelve a seleccionar la captura antes de confirmarla.", 409)
            if code_hash(record["code"]) != digest:
                raise AppError("Guarda el mismo código que acabas de probar.", 409)
            record["physical_result"] = "worked" if worked else "failed"
            record["verification"] = {"reported_by": "user", "at": now()}
            record["updated_at"] = now()
            record["revision"] += 1
            self._write(record)
            return record


class DemoRadio:
    """Datos sintéticos para revisar la interfaz; nunca abre sockets de dispositivo."""
    def capture(self, cancel, progress, frequency="0", seconds=30):
        progress("Demostración: preparando una señal de ejemplo.")
        if cancel.wait(1.5):
            raise AppError("Captura cancelada.")
        raw = {"num": 1, "ver": "2", "study_feq": "433.92", "data0": "AQIDBA==", "lv": [0]}
        code = base64.b64encode(json.dumps(raw, separators=(",", ":")).encode()).decode()
        checked = validate_code(code)
        return {"code": code, "summary": checked["summary"], "source_dp": "202", "origin": "demo", "physical_verified": False}

    def send(self, code, times=1, progress=None):
        validate_code(code)
        return {"outcome": "NOT_SENT", "problem": "DEMO", "frame_write_attempted": False, "physical_verified": False, "times": times,
                "timing_ms": {"prepare": 1, "arp": None, "connect": None, "write": None, "response": None, "total": 1}}


class TrialLog:
    """Historial DPAPI local: parámetros y resultados, sin códigos ni claves."""
    def __init__(self, directory):
        self.path = Path(directory) / "historial.rfjournal"
        self.lock = threading.RLock()

    def _read(self):
        try:
            value = json.loads(unseal(self.path.read_bytes()))
            if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
                raise ValueError()
            return value
        except FileNotFoundError:
            return []
        except (OSError, ValueError, RfError):
            raise AppError("No se pudo leer el historial cifrado de ensayos.") from None

    def _write(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / ("." + secrets.token_hex(16) + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(seal(json.dumps(rows, ensure_ascii=False).encode("utf-8")))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self):
        with self.lock:
            return list(reversed(self._read()[-50:]))

    def append(self, row):
        with self.lock:
            rows = self._read()
            if any(previous["id"] == row["id"] for previous in rows):
                return
            rows.append(row)
            self._write(rows[-500:])

    def observe(self, operation_id, worked):
        checked_id(operation_id)
        with self.lock:
            rows = self._read()
            for row in rows:
                if row["id"] != operation_id:
                    continue
                if row.get("demo") or not row.get("frame_write_attempted"):
                    raise AppError("Este ensayo no transmitió una orden real.")
                row.update(physical_result="worked" if worked else "failed", reported_at=now(), reported_by="user")
                self._write(rows)
                return row
        raise AppError("No se encontró este ensayo.", 404)


class Application:
    def __init__(self, credential, directory, demo=False, radio=None):
        self.csrf = secrets.token_urlsafe(32)
        self.demo = demo
        self.library = Library(directory)
        self.trials = TrialLog(directory)
        self.device = credential_info(credential) if not demo else {"host": "Equipo simulado", "mac": "", "port": 6668, "version": "3.3", "ready": True}
        self.radio = radio or (DemoRadio() if demo else Radio(credential))
        self.lock = threading.RLock()
        self.operation = None
        self.requests = {}
        self.test_digests = {}
        self.cancel = threading.Event()
        self.worker = None

    def state(self):
        captures, unreadable = self.library.list()
        try:
            trials, history_error = self.trials.list(), False
        except AppError:
            trials, history_error = [], True
        return {"device": self.device, "captures": captures, "unreadable_captures": unreadable, "operation": self.operation_state(), "demo": self.demo,
                "trials": trials, "history_error": history_error, "version": "1.0.0"}

    def operation_state(self):
        with self.lock:
            operation = dict(self.operation) if self.operation else None
            if operation:
                operation.pop("started", None)
            return operation

    def _start(self, kind, run, request_id=None, on_result=None):
        with self.lock:
            if request_id and request_id in self.requests:
                return dict(self.requests[request_id])
            if self.operation and self.operation["phase"] == "running":
                raise AppError("Ya hay una captura o prueba en curso.", 409)
            if request_id and len(self.requests) >= 4096:
                raise AppError("Reinicia la aplicación para iniciar una nueva sesión.", 409)
            self.cancel = threading.Event()
            operation = {"id": str(uuid.uuid4()), "kind": kind, "phase": "running", "message": "Preparando la captura…" if kind == "capture" else "Enviando una orden de prueba…"}
            self.operation = operation
            if request_id:
                self.requests[request_id] = operation

            def progress(message):
                with self.lock:
                    operation["message"] = message

            def work():
                try:
                    result = run(self.cancel, progress)
                    if on_result is not None:
                        try:
                            on_result(operation, result)
                            result["history_saved"] = True
                        except Exception:
                            # La orden ya terminó; un fallo de disco nunca permite reenviarla.
                            result["history_saved"] = False
                    with self.lock:
                        operation.update(phase="done", message="Captura recibida. Ponle un nombre y guárdala." if kind == "capture" else "Prueba terminada.", result=result)
                except (RfError, AppError) as error:
                    with self.lock:
                        operation.update(phase="error", message=str(error) if isinstance(error, AppError) else rf_message(error))
                        if isinstance(error, RfError):
                            operation["problem"] = error.code
                            if error.cleanup_sent is not None:
                                operation["learning_exit_sent"] = error.cleanup_sent
                                if not error.cleanup_sent:
                                    operation["message"] += " No se pudo confirmar el envío de salida del aprendizaje."
                except Exception:
                    with self.lock:
                        operation.update(phase="error", message="No se pudo completar la operación. Revisa la conexión y vuelve a iniciar una acción manual.")
            self.worker = threading.Thread(target=work, name="rf-operation", daemon=False)
            self.worker.start()
            return dict(operation)

    def capture(self, data):
        frequency = data.get("frequency", "0")
        if frequency not in ("0", "433.92"):
            raise AppError("Elige frecuencia automática o 433.92 MHz.")
        if not self.device.get("ready"):
            raise AppError("No se pudo leer la credencial DPAPI. Abre la aplicación con la misma cuenta de Windows.")
        return self._start("capture", lambda cancel, progress: self.radio.capture(cancel, progress, frequency=frequency, seconds=30))

    def test(self, data):
        request_id = checked_id(data.get("request_id"))
        checked = validate_code(data.get("code"))
        times = data.get("times", 1)
        if type(times) is not int or not 1 <= times <= 6:
            raise AppError("Las repeticiones deben ser un entero entre 1 y 6.")
        if not self.device.get("ready"):
            raise AppError("No se pudo leer la credencial DPAPI.")
        name = data.get("name", "Borrador")
        if not isinstance(name, str) or len(name) > 100:
            raise AppError("El nombre del control admite hasta 100 caracteres.")

        def record_trial(operation, result):
            self.trials.append({"id": operation["id"], "at": now(), "name": name.strip() or "Borrador",
                "times": times, "outcome": result["outcome"], "problem": result["problem"],
                "frame_write_attempted": result["frame_write_attempted"],
                "timing_ms": result.get("timing_ms", {}), "physical_result": "unverified", "demo": self.demo})

        digest = code_hash(checked["canonical_code"])
        with self.lock:
            operation = self._start("test", lambda cancel, progress: self.radio.send(checked["canonical_code"], times=times, progress=progress), request_id, record_trial)
            self.test_digests.setdefault(operation["id"], digest)
            return operation

    def verify(self, data):
        if type(data.get("worked")) is not bool:
            raise AppError("Indica si funcionó el control.")
        with self.lock:
            operation = self.operation
            operation_id = data.get("operation_id")
            if (self.demo or not operation or operation["id"] != operation_id or operation["kind"] != "test"
                    or operation["phase"] != "done" or not operation.get("result", {}).get("frame_write_attempted")):
                raise AppError("Primero realiza una prueba con este código. La demostración no acciona equipos.")
            digest = self.test_digests.get(operation_id)
        return self.library.verify(data.get("capture_id"), data.get("revision"), digest, data["worked"])

    def observe_trial(self, data):
        if self.demo:
            raise AppError("La demostración no acciona equipos.")
        if type(data.get("worked")) is not bool:
            raise AppError("Indica si funcionó el control.")
        return self.trials.observe(data.get("operation_id"), data["worked"])

    def close(self):
        self.cancel.set()
        if self.worker:
            self.worker.join(timeout=6)


def rf_message(error):
    # RfError contiene exclusivamente mensajes del módulo de dispositivo.
    return str(error) or "El L20 no pudo completar la operación."


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # No imprimir trazas que pudieran contener códigos recibidos.
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "L20-RF-LAN/1.0"

    def log_message(self, *args):
        pass

    def _origin_ok(self):
        hosts = {"127.0.0.1:" + str(self.server.server_port), "localhost:" + str(self.server.server_port)}
        if self.headers.get("Host") not in hosts:
            raise AppError("Abre la aplicación desde su dirección local.", 403)
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + host for host in hosts}:
            raise AppError("Solicitud externa rechazada.", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise AppError("Solicitud externa rechazada.", 403)

    def _reply(self, value, status=200, content_type="application/json; charset=utf-8"):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, post=False):
        self._origin_ok()
        app = self.server.app
        path = urlsplit(self.path).path
        if not post:
            if path == "/api/session":
                return self._reply({"csrf": app.csrf, "demo": app.demo})
            if path == "/api/state":
                return self._reply(app.state())
            if path == "/api/operation":
                return self._reply({"operation": app.operation_state()})
            if path.startswith("/api/captures/"):
                return self._reply({"record": app.library.get(path.rsplit("/", 1)[1])})
            files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.css": ("app.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8")}
            if path in files:
                filename, kind = files[path]
                return self._reply((ROOT / "static" / filename).read_bytes(), content_type=kind)
            raise AppError("No se encontró esta página.", 404)
        if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), app.csrf):
            raise AppError("La sesión cambió. Recarga la página.", 403)
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise AppError("Se necesita una solicitud JSON.", 415)
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            raise AppError("Tamaño de solicitud inválido.") from None
        if not 0 <= length <= MAX_BODY:
            raise AppError("La solicitud es demasiado grande.", 413)
        self.connection.settimeout(5)
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise AppError("JSON inválido.") from None
        if not isinstance(data, dict):
            raise AppError("Solicitud inválida.")
        if path == "/api/validate":
            checked = validate_code(data.get("code"))
            return self._reply({"code": checked["canonical_code"], "summary": checked["summary"]})
        if path == "/api/captures":
            return self._reply({"record": app.library.save(data)})
        if path == "/api/capture/start":
            return self._reply({"operation": app.capture(data)}, 202)
        if path == "/api/capture/cancel":
            with app.lock:
                if app.operation and app.operation["kind"] == "capture" and app.operation["phase"] == "running":
                    app.cancel.set()
            return self._reply({"ok": True})
        if path == "/api/test":
            return self._reply({"operation": app.test(data)}, 202)
        if path == "/api/verification":
            return self._reply({"record": app.verify(data)})
        if path == "/api/trial-result":
            return self._reply({"trial": app.observe_trial(data)})
        raise AppError("Operación desconocida.", 404)

    def _handle(self, post):
        try:
            self._dispatch(post)
        except AppError as error:
            self._reply({"error": error.message}, error.status)
        except RfError as error:
            self._reply({"error": rf_message(error)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._reply({"error": "No se pudo completar la solicitud local."}, 500)

    def do_GET(self):
        self._handle(False)

    def do_POST(self):
        self._handle(True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="L20 RF LAN: interfaz web local para Windows")
    parser.add_argument("--port", type=int, default=58745)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIAL)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("El puerto web debe estar entre 1 y 65535.")
    if os.name != "nt":
        print("Esta versión necesita Windows para DPAPI y la comprobación ARP.", flush=True)
        return 2
    directory = args.data or ROOT / ("datos-demo" if args.demo else "datos") / "capturas"
    application = Application(args.credentials, directory, args.demo)
    try:
        server = Server(("127.0.0.1", args.port), Handler)
    except OSError:
        print("No se pudo abrir el puerto local. Cierra la instancia anterior o usa --port con otro número.", flush=True)
        return 1
    server.app = application
    url = "http://127.0.0.1:" + str(server.server_port)
    print("L20 RF LAN 1.0.0" + (" | demostración sin equipo" if args.demo else " | L20 local"), flush=True)
    print(url, flush=True)
    print("Capturas cifradas con tu cuenta de Windows. Ctrl+C para cerrar.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        application.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
