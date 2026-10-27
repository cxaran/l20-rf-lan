"""Local L20 RF transport. Importing and constructing Radio never use the network.

Only explicit capture()/send() open one connection. An ACK proves receipt of a
request, never RF emission or gate movement. A captured report may be old data.
"""
from __future__ import annotations

import base64
import binascii
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import ipaddress
import json
import math
from pathlib import Path
import re
import secrets
import socket
import struct
import threading
import time
import zlib

PORT, VERSION = 6668, "3.3"
MAX_FRAME, MAX_CODE = 65536, 32768
_PREFIX, _SUFFIX = b"\x00\x00\x55\xaa", b"\x00\x00\xaa\x55"
_VERSION = b"3.3" + bytes(12)
_RADIO_LOCK, _ARP_LOCK = threading.Lock(), threading.Lock()
_MESSAGES = {
    "INVALID_INPUT": "El código o los parámetros no tienen el formato admitido.",
    "INVALID_CREDENTIALS": "No se pudo leer una credencial válida del L20 con esta cuenta de Windows.",
    "DPAPI_ERROR": "Windows no pudo proteger o descifrar los datos con esta cuenta.",
    "MAC_MISMATCH": "La MAC de la dirección configurada no corresponde al L20.",
    "ARP_UNAVAILABLE": "No se pudo comprobar la MAC del L20 en Windows.",
    "BUSY": "Ya hay una operación de radio en curso.",
    "TIMEOUT": "Terminó el plazo de comunicación con el L20.",
    "CANCELLED": "Captura cancelada.",
    "NO_CODE": "Terminó la escucha sin un contenedor RF válido.",
    "IO": "No se pudo completar la comunicación con el L20.",
    "REMOTE_EOF": "El L20 cerró la conexión durante la escucha.",
    "INVALID_FRAME": "La respuesta del L20 no tiene un formato válido.",
    "KEY_OR_VERSION": "No se pudo validar el descifrado de la respuesta del L20.",
    "DEVICE_REJECTED": "El L20 rechazó la solicitud.",
    "INTERNAL_ERROR": "La operación no pudo completarse.",
}


class RfError(Exception):
    """A fixed, safe error; never includes credentials, RF data or raw errors."""
    def __init__(self, code):
        self.code = code if code in _MESSAGES else "INTERNAL_ERROR"
        self.cleanup_sent = None
        super().__init__(_MESSAGES[self.code])


@dataclass(frozen=True)
class Credentials:
    """Validated LAN configuration; secrets are excluded from representation."""
    target_ip: str
    target_mac: str
    device_id: str = field(repr=False)
    local_key: bytes = field(repr=False)
    port: int = PORT
    version: str = VERSION


def validate_credentials(value):
    """Validate a private IPv4 LAN destination and the supported Tuya profile."""
    try:
        if not isinstance(value, dict):
            raise ValueError()
        host, mac = value.get("target_ip"), value.get("target_mac")
        if not isinstance(host, str) or not isinstance(mac, str):
            raise ValueError()
        address = ipaddress.IPv4Address(host.strip())
        if (not address.is_private or address.is_loopback or address.is_multicast
                or address.is_unspecified or address.is_reserved):
            raise ValueError()
        mac = mac.strip().upper()
        if re.fullmatch(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}", mac) is None:
            raise ValueError()
        octets = bytes.fromhex(mac.replace(":", ""))
        if octets == bytes(6) or octets[0] & 1:
            raise ValueError()
        port, version = value.get("port", PORT), value.get("version", VERSION)
        if type(port) is not int or port != PORT or version not in (VERSION, 3.3):
            raise ValueError()
        device_id, key = value.get("device_id"), value.get("local_key")
        if not isinstance(device_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", device_id) is None:
            raise ValueError()
        if not isinstance(key, str) or len(key.encode("latin1")) != 16:
            raise ValueError()
        return Credentials(str(address), mac, device_id, key.encode("latin1"), PORT, VERSION)
    except Exception:
        raise RfError("INVALID_CREDENTIALS") from None


def _object(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    def constant(_):
        raise ValueError()
    if not isinstance(text, str) or len(text) > MAX_FRAME:
        raise ValueError()
    # Bound nesting before json.loads so hostile editor input cannot recurse.
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 12:
                raise ValueError()
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError()
    if depth or quoted:
        raise ValueError()
    result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(result, dict):
        raise ValueError()
    return result


def _base64(text):
    if (not isinstance(text, str) or not 0 < len(text) <= MAX_CODE
            or len(text) % 4 or re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", text) is None):
        raise ValueError()
    raw = base64.b64decode(text, validate=True)
    if not raw or base64.b64encode(raw).decode("ascii") != text:
        raise ValueError()
    return raw


def validate_code(text):
    """Validate a complete Base64 Tuya RF v2 container without rewriting it."""
    try:
        code = text.strip() if isinstance(text, str) else text
        obj = _object(_base64(code).decode("utf-8"))
        if not (obj.get("ver") == "2" or type(obj.get("ver")) is int and obj["ver"] == 2):
            raise ValueError()
        if type(obj.get("num")) is not int or obj["num"] != 1:
            raise ValueError()
        _base64(obj.get("data0"))
        levels = obj.get("lv")
        if (not isinstance(levels, list) or len(levels) != 1
                or type(levels[0]) is not int or levels[0] not in (0, 1)):
            raise ValueError()
        if any(re.fullmatch(r"data[0-9]+", key) and key != "data0" for key in obj):
            raise ValueError()
        frequency = None
        for name in ("study_feq", "feq"):
            if name in obj:
                value = obj[name]
                if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                    raise ValueError()
                value = float(value)
                if not math.isfinite(value) or value != 0 and not 250 <= value <= 1000:
                    raise ValueError()
                if frequency is None and value:
                    frequency = value
        return {"canonical_code": code, "summary": {
            "version": "2", "num": 1, "frequency": frequency, "length": len(code)}}
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError):
        raise RfError("INVALID_INPUT") from None


def _dpapi(data, protect):
    limit = 8 * 1024 * 1024 + (0 if protect else 65536)
    if not isinstance(data, bytes) or not 0 < len(data) <= limit:
        raise RfError("INVALID_INPUT")
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    source_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), source_buffer), Blob()
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypto.CryptProtectData if protect else crypto.CryptUnprotectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p,
        ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
    try:
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise ValueError()
        if not 0 < result.size <= 8 * 1024 * 1024 + 65536:
            raise ValueError()
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.memset(source_buffer, 0, len(data))
        if result.data:
            ctypes.memset(result.data, 0, result.size)
            kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def seal(data):
    """Protect bytes for the current Windows user and machine (no file writes)."""
    try:
        return _dpapi(data, True)
    except Exception:
        raise RfError("DPAPI_ERROR") from None


def unseal(data):
    """Unprotect bytes locally; callers choose the storage path and format."""
    try:
        return _dpapi(data, False)
    except Exception:
        raise RfError("DPAPI_ERROR") from None


def load_credentials(path):
    try:
        file = Path(path)
        if not 0 < file.stat().st_size <= MAX_FRAME:
            raise ValueError()
        obj = _object(unseal(file.read_bytes()).decode("utf-8"))
        return validate_credentials(obj)
    except Exception:
        raise RfError("INVALID_CREDENTIALS") from None


def credential_info(path):
    """Read DPAPI locally; expose destination metadata without identifiers/keys."""
    try:
        credential = load_credentials(path)
        return {"host": credential.target_ip, "mac": credential.target_mac,
                "port": credential.port, "version": credential.version, "ready": True}
    except RfError:
        return {"host": "", "mac": "", "port": None, "version": "", "ready": False}


def _arp_mac(host):
    arp = ctypes.WinDLL("iphlpapi", use_last_error=True).SendARP
    arp.argtypes = [wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
    arp.restype = wintypes.DWORD
    data, size = (ctypes.c_ubyte * 8)(), wintypes.ULONG(6)
    address = struct.unpack("=I", socket.inet_aton(host))[0]
    if arp(address, 0, data, ctypes.byref(size)) or size.value != 6:
        raise ValueError()
    return ":".join(f"{part:02X}" for part in data[:6])


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise RfError("TIMEOUT")
    return value


def _check_mac(host, mac, deadline, cancel=None):
    # SendARP has no timeout. Its isolated daemon can only check ARP, never TCP.
    # Hold this lock until native completion, preventing abandoned-worker buildup.
    if cancel is not None and cancel.is_set():
        raise RfError("CANCELLED")
    _remaining(deadline)
    if not _ARP_LOCK.acquire(blocking=False):
        raise RfError("BUSY")
    done, state = threading.Event(), {}
    def worker():
        try:
            state["mac"] = _arp_mac(host)
        except Exception:
            state["failed"] = True
        finally:
            _ARP_LOCK.release()
            done.set()
    try:
        threading.Thread(target=worker, name="rf-arp-check", daemon=True).start()
    except Exception:
        _ARP_LOCK.release()
        raise RfError("ARP_UNAVAILABLE") from None
    while not done.wait(min(.05, _remaining(deadline))):
        if cancel is not None and cancel.is_set():
            raise RfError("CANCELLED")
    _remaining(deadline)
    if cancel is not None and cancel.is_set():
        raise RfError("CANCELLED")
    if state.get("failed"):
        raise RfError("ARP_UNAVAILABLE")
    if state.get("mac") != mac:
        raise RfError("MAC_MISMATCH")


def _cipher(key):
    from tinytuya.core.crypto_helper import AESCipher
    return AESCipher(key)


def _frame(command, device_id, key, sequence):
    body = {"devId": device_id, "uid": device_id, "t": str(int(time.time())),
            "dps": {"201": json.dumps(command, separators=(",", ":"))}}
    encrypted = _cipher(key).encrypt(json.dumps(body, separators=(",", ":")).encode("utf-8"), use_base64=False)
    payload = _VERSION + encrypted
    header = struct.pack(">4I", 0x55AA, sequence, 7, len(payload) + 8)
    result = header + payload
    if len(result) + 8 > MAX_FRAME:
        raise RfError("INVALID_INPUT")
    return result + struct.pack(">2I", zlib.crc32(result) & 0xffffffff, 0xAA55)


def _decode(payload, key):
    try:
        if payload.startswith(b"3.3"):
            # Device responses may use the twelve reserved bytes as metadata.
            # TinyTuya removes the whole header without requiring zero bytes.
            if len(payload) < 15:
                raise ValueError()
            payload = payload[15:]
        if not payload or len(payload) % 16:
            raise ValueError()
        plain = _cipher(key).decrypt(payload, use_base64=False, decode_text=False, verify_padding=True)
        text = plain.decode("utf-8").strip()
        if text in ("json obj data unvalid", "data unvalid", "json data unvalid"):
            raise RfError("DEVICE_REJECTED")
        obj = _object(text)
        if any(name in obj for name in ("error", "err", "Err")) or obj.get("success") is False:
            raise RfError("DEVICE_REJECTED")
        return obj
    except RfError:
        raise
    except Exception:
        raise RfError("KEY_OR_VERSION") from None


class _Reader:
    """Bounded 55AA stream parser; fragments survive idle receive ticks."""
    def __init__(self, connection):
        self.connection, self.buffer = connection, bytearray()

    def _pop(self):
        while self.buffer:
            if not self.buffer.startswith(_PREFIX):
                index = self.buffer.find(_PREFIX)
                if index < 0:
                    del self.buffer[:max(0, len(self.buffer) - 3)]
                    return None
                del self.buffer[:index]
            if len(self.buffer) < 16:
                return None
            _, sequence, command, length = struct.unpack_from(">4I", self.buffer)
            total = length + 16
            if length < 12 or total > MAX_FRAME:
                del self.buffer[0]
                continue
            if len(self.buffer) < total:
                return None
            raw = bytes(self.buffer[:total])
            crc = struct.unpack_from(">I", raw, total - 8)[0]
            if raw[-4:] != _SUFFIX or crc != zlib.crc32(raw[:-8]) & 0xffffffff:
                del self.buffer[0]
                continue
            del self.buffer[:total]
            return sequence, command, struct.unpack_from(">I", raw, 16)[0], raw[20:-8]
        return None

    def read(self, deadline, cancel=None):
        tick = min(deadline, time.monotonic() + .4)
        while True:
            if cancel is not None and cancel.is_set():
                raise RfError("CANCELLED")
            _remaining(deadline)
            frame = self._pop()
            if frame is not None:
                _remaining(deadline)
                return frame
            remaining = tick - time.monotonic()
            if remaining <= 0:
                return None
            self.connection.settimeout(min(.2, remaining))
            try:
                chunk = self.connection.recv(min(4096, MAX_FRAME - len(self.buffer)))
            except socket.timeout:
                continue
            if not chunk:
                raise RfError("REMOTE_EOF")
            if len(chunk) > MAX_FRAME - len(self.buffer):
                raise RfError("INVALID_FRAME")
            self.buffer.extend(chunk)


def _open(host, port, deadline):
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        connection.settimeout(min(1.5, _remaining(deadline)))
        connection.connect((host, port))
        _remaining(deadline)
        return connection
    except Exception:
        connection.close()
        raise


def _dps(obj):
    for _ in range(5):
        if not isinstance(obj, dict):
            break
        if isinstance(obj.get("dps"), dict):
            return obj["dps"]
        obj = obj.get("data")
    return {}


def _notify(progress, text):
    if callable(progress):
        try:
            progress(text)
        except Exception:
            pass


class Radio:
    def __init__(self, credential_path):
        self.credential_path = Path(credential_path)

    def capture(self, cancel, progress, frequency="0", seconds=30):
        """Start/exit learning once. Returned data has no proven fresh RF origin."""
        if (frequency not in ("0", "433.92") or isinstance(seconds, bool)
                or not isinstance(seconds, (int, float)) or not math.isfinite(seconds)
                or not 1 <= seconds <= 120 or not isinstance(cancel, threading.Event)):
            raise RfError("INVALID_INPUT")
        if not _RADIO_LOCK.acquire(blocking=False):
            raise RfError("BUSY")
        connection, started, cleanup, result, error = None, False, False, None, None
        try:
            if cancel.is_set():
                raise RfError("CANCELLED")
            credential = load_credentials(self.credential_path)
            device_id, key = credential.device_id, credential.local_key
            _notify(progress, "Comprobando el L20…")
            prepare_deadline = time.monotonic() + 4
            _check_mac(credential.target_ip, credential.target_mac, prepare_deadline, cancel)
            connection = _open(credential.target_ip, credential.port, prepare_deadline)
            if cancel.is_set():
                raise RfError("CANCELLED")
            sequence = secrets.randbelow(0xfffffffe) + 1
            command = {"control": "rf_study", "rf_type": "sub_2g", "study_feq": frequency, "ver": "2"}
            frame = _frame(command, device_id, key, sequence)
            connection.settimeout(_remaining(prepare_deadline))
            started = True  # A partial send can reach the device.
            connection.sendall(frame)
            deadline, reader = time.monotonic() + seconds, _Reader(connection)
            _notify(progress, "Escuchando. Una señal recibida puede corresponder a datos anteriores.")
            last_second = None
            while True:
                if time.monotonic() >= deadline:
                    raise RfError("NO_CODE")
                remaining = math.ceil(deadline - time.monotonic())
                if remaining != last_second:
                    _notify(progress, f"Escuchando: {remaining} s restantes.")
                    last_second = remaining
                try:
                    frame = reader.read(deadline, cancel)
                except RfError as exc:
                    if exc.code == "TIMEOUT":
                        raise RfError("NO_CODE") from None
                    raise
                if frame is None:
                    continue
                _, command_number, return_code, payload = frame
                if command_number not in (7, 8, 10, 16):
                    continue
                if return_code:
                    raise RfError("DEVICE_REJECTED")
                if not payload:
                    continue
                obj = _decode(payload, key)
                dps = _dps(obj)
                for dp in ("202", "2"):
                    if dp not in dps:
                        continue
                    try:
                        candidate = validate_code(dps[dp])
                    except RfError:
                        continue
                    result = {"code": candidate["canonical_code"], "summary": candidate["summary"],
                        "source_dp": dp, "origin": "received_during_learning", "physical_verified": False}
                    break
                if result:
                    break
        except RfError as exc:
            error = exc
        except socket.timeout:
            error = RfError("TIMEOUT")
        except OSError:
            error = RfError("IO")
        except Exception:
            error = RfError("INTERNAL_ERROR")
        finally:
            if connection is not None:
                if started:
                    _notify(progress, "Terminando el aprendizaje…")
                    try:
                        command = {"control": "rfstudy_exit", "rf_type": "sub_2g", "study_feq": frequency, "ver": "2"}
                        connection.settimeout(1)
                        connection.sendall(_frame(command, device_id, key, sequence + 1))
                        cleanup = True
                    except Exception:
                        pass
                try:
                    connection.close()
                except OSError:
                    pass
            _RADIO_LOCK.release()
        if error:
            error.cleanup_sent = cleanup if started else None
            raise error
        result["learning_exit_sent"] = cleanup
        return result

    def send(self, code, times=1, progress=None):
        """Attempt one CONTROL7 write, with no retries or implicit replays."""
        attempted, connection = False, None
        started = time.monotonic()
        timing = {name: None for name in ("prepare", "arp", "connect", "write", "response", "total")}
        phase, phase_started = None, started
        safe_times = times if type(times) is int and 1 <= times <= 6 else 1
        def next_phase(name):
            nonlocal phase, phase_started
            now = time.monotonic()
            if phase is not None:
                timing[phase] = round(max(0.0, (now - phase_started) * 1000), 3)
            phase, phase_started = name, now
        def outcome(value, problem):
            next_phase(None)
            timing["total"] = round(max(0.0, (time.monotonic() - started) * 1000), 3)
            return {"outcome": value, "problem": problem,
                    "frame_write_attempted": attempted, "physical_verified": False,
                    "times": safe_times, "timing_ms": timing}
        if not _RADIO_LOCK.acquire(blocking=False):
            return outcome("NOT_SENT", "BUSY")
        try:
            next_phase("prepare")
            if type(times) is not int or not 1 <= times <= 6:
                raise RfError("INVALID_INPUT")
            canonical = validate_code(code)["canonical_code"]
            credential = load_credentials(self.credential_path)
            device_id, key = credential.device_id, credential.local_key
            sequence = secrets.randbelow(0xffffffff)
            command = {"control": "rfstudy_send", "rf_type": "sub_2g", "feq": 0,
                "mode": 0, "rate": 0, "ver": "2", "key1": {
                    "code": canonical, "times": times, "delay": 0, "intervals": 0}}
            encoded = _frame(command, device_id, key, sequence)
            deadline = time.monotonic() + 4
            next_phase("arp")
            _check_mac(credential.target_ip, credential.target_mac, deadline)
            next_phase("connect")
            connection = _open(credential.target_ip, credential.port, deadline)
            connection.settimeout(_remaining(deadline))
            next_phase("write")
            attempted = True
            connection.sendall(encoded)
            next_phase("response")
            _notify(progress, "Orden enviada al L20; esperando respuesta.")
            reader, frames = _Reader(connection), 0
            while frames < 8:
                frame = reader.read(deadline)
                if frame is None:
                    continue
                frames += 1
                received_sequence, command_number, return_code, payload = frame
                if received_sequence != sequence or command_number != 7:
                    continue
                if return_code:
                    return outcome("DEVICE_REJECTED", "DEVICE_REJECTED")
                if not payload:
                    return outcome("ACKNOWLEDGED", "NONE")
                obj = _decode(payload, key)
                if obj.get("success") is True or _dps(obj):
                    return outcome("ACKNOWLEDGED", "NONE")
                raise RfError("INVALID_FRAME")
            raise RfError("INVALID_FRAME")
        except RfError as exc:
            if exc.code == "DEVICE_REJECTED" and attempted:
                return outcome("DEVICE_REJECTED", exc.code)
            return outcome("UNCERTAIN" if attempted else "NOT_SENT", exc.code)
        except socket.timeout:
            return outcome("UNCERTAIN" if attempted else "NOT_SENT", "TIMEOUT")
        except OSError:
            return outcome("UNCERTAIN" if attempted else "NOT_SENT", "IO")
        except Exception:
            return outcome("UNCERTAIN" if attempted else "NOT_SENT", "INTERNAL_ERROR")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            _RADIO_LOCK.release()
            # Returned dictionaries reference timing, so finalization includes
            # close time in total without changing the transport result.
            timing["total"] = round(max(0.0, (time.monotonic() - started) * 1000), 3)
