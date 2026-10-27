"""Interactive credential setup. No import-time I/O, LAN discovery or RF.

The optional Cloud SDK runs in a bounded child process. Its credentials travel
through stdin and its device list through a private stdout pipe, never argv,
environment variables, credential files or console output.
"""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
import getpass
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
import warnings

from credential_store import CredentialStoreError, check_destination, write_credentials
from rf_device import RfError, seal, validate_credentials

MAX_JSON = 2 * 1024 * 1024
CLOUD_TIMEOUT = 20
REGIONS = ("cn", "us", "us-e", "eu", "eu-w", "in", "sg")
_DEMO_IP, _DEMO_MAC = "10.23.45.67", "02:00:00:23:45:67"


class SetupError(Exception):
    """Fixed messages only; never wrap SDK output or user-provided secrets."""


@dataclass(frozen=True)
class _Candidate:
    name: str
    device_id: str = field(repr=False)
    local_key: str = field(repr=False)
    mac: str = ""
    port: object = 6668
    version: object = "3.3"


def _strict_json(raw, limit=MAX_JSON):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
        raise SetupError("El JSON está vacío o supera el tamaño admitido.")
    try:
        text = raw.decode("utf-8-sig")
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
                if depth > 16:
                    raise ValueError()
            elif char in "]}":
                depth -= 1
                if depth < 0:
                    raise ValueError()
        if depth or quoted:
            raise ValueError()
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        def constant(_):
            raise ValueError()
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise SetupError("El archivo no contiene un JSON válido y sin claves duplicadas.") from None


def _alias(row, first, second):
    if first in row and second in row and row[first] != row[second]:
        raise SetupError("Un registro contiene identificadores o claves ambiguos.")
    return row.get(first, row.get(second, ""))


def _label(value, redactions=()):
    if not isinstance(value, str):
        return "Dispositivo sin nombre"
    clean = "".join(char for char in value if not unicodedata.category(char).startswith("C"))
    for secret in redactions:
        if isinstance(secret, str) and secret:
            clean = clean.replace(secret, "[dato oculto]")
    return " ".join(clean.split())[:80] or "Dispositivo sin nombre"


def _records(value, *, redactions=()):
    if isinstance(value, dict):
        value = value.get("devices")
    if not isinstance(value, list) or not 1 <= len(value) <= 2000:
        raise SetupError("Se necesita una lista de dispositivos o un objeto con una lista devices.")
    secret_fields = {"id", "deviceid", "key", "localkey", "apikey", "apisecret",
                     "accessid", "accesssecret", "token", "accesstoken", "secret"}
    redactions = list(redactions) + [item for row in value if isinstance(row, dict)
        for name, item in row.items() if name.lower().replace("_", "") in secret_fields]
    result, seen = [], set()
    for row in value:
        if not isinstance(row, dict):
            raise SetupError("La lista contiene un registro de dispositivo inválido.")
        device_id, key = _alias(row, "device_id", "id"), _alias(row, "local_key", "key")
        if not isinstance(device_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", device_id) is None:
            raise SetupError("La lista contiene un identificador de dispositivo inválido.")
        if device_id in seen:
            raise SetupError("La lista contiene identificadores duplicados; selecciona una fuente sin ambigüedades.")
        seen.add(device_id)
        if not isinstance(key, str):
            raise SetupError("La lista contiene una clave local con formato inválido.")
        mac = row.get("target_mac", row.get("mac", ""))
        result.append(_Candidate(_label(row.get("name"), redactions), device_id, key,
            mac if isinstance(mac, str) else "", row.get("port", 6668), row.get("version", "3.3")))
    return result


def _masked(identifier):
    return "••••" if len(identifier) <= 6 else identifier[:3] + "••••" + identifier[-3:]


def _choose(records):
    # Names are untrusted terminal text and may accidentally contain a key.
    redactions = [value for record in records for value in (record.device_id, record.local_key) if value]
    for index, record in enumerate(records, 1):
        name = record.name
        for secret in redactions:
            name = name.replace(secret, "[dato oculto]")
        print(f"{index}. {name} · ID {_masked(record.device_id)}")
    answer = input("Número del dispositivo que deseas configurar: ").strip()
    if not re.fullmatch(r"[0-9]{1,4}", answer) or not 1 <= int(answer) <= len(records):
        raise SetupError("Selecciona un único dispositivo mediante un número de la lista.")
    return records[int(answer) - 1]


def _hidden(prompt):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(prompt)
    except (Exception,):
        raise SetupError("No se pudo obtener una entrada oculta. Abre una consola interactiva de Windows.") from None


class _Discard:
    def write(self, text):
        return len(text)
    def flush(self):
        pass


@contextmanager
def _quiet_sdk():
    # Used only inside the child in production; restore state for isolated tests.
    previous = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with redirect_stdout(_Discard()), redirect_stderr(_Discard()):
            yield
    finally:
        logging.disable(previous)


def _cloud_query(region, api_id, api_secret, sample_device_id):
    if (region not in REGIONS or not isinstance(api_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", api_id) is None
            or not isinstance(api_secret, str) or not 1 <= len(api_secret) <= 256
            or not all(char.isprintable() for char in api_secret)
            or not api_secret.strip() or not isinstance(sample_device_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sample_device_id) is None):
        raise SetupError("Revisa la región y los datos del proyecto Tuya IoT.")
    return {"region": region, "api_id": api_id, "api_secret": api_secret,
            "sample_device_id": sample_device_id}


def _fetch_cloud(query):
    """SDK-only child operation: Cloud reads, no LAN methods or file helpers."""
    query = _cloud_query(**query)
    with _quiet_sdk():
        import tinytuya
        cloud = tinytuya.Cloud(apiRegion=query["region"], apiKey=query["api_id"],
            apiSecret=query["api_secret"], apiDeviceID=query["sample_device_id"],
            new_sign_algorithm=True, initial_token=None, configFile="")
        try:
            if getattr(cloud, "error", None):
                raise SetupError("Tuya Cloud no pudo autenticar el proyecto indicado.")
            raw = cloud.getdevices(verbose=False, include_map=False)
            records = _records(raw, redactions=query.values())
            safe = []
            for record in records:
                name = record.name
                for secret in query.values():
                    name = name.replace(secret, "[dato oculto]")
                safe.append({"name": name, "device_id": record.device_id,
                    "local_key": record.local_key, "mac": record.mac,
                    "port": record.port, "version": record.version})
            return safe
        finally:
            # Clear the SDK's references before child exit; never persist tokens.
            for name in ("apiKey", "apiSecret", "apiDeviceID", "token", "getdevices_raw"):
                if hasattr(cloud, name):
                    setattr(cloud, name, None)


def _cloud_worker():
    try:
        query = _strict_json(sys.stdin.buffer.read(4097), 4096)
        if not isinstance(query, dict) or set(query) != {"region", "api_id", "api_secret", "sample_device_id"}:
            raise SetupError("Solicitud Cloud inválida.")
        response = {"ok": True, "devices": _fetch_cloud(query)}
        encoded = json.dumps(response, ensure_ascii=True).encode("ascii")
        if len(encoded) > MAX_JSON:
            raise SetupError("La lista Cloud supera el tamaño admitido.")
    except Exception:
        encoded = b'{"ok":false}'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _cloud_devices(region, api_id, api_secret, sample_device_id):
    query = _cloud_query(region, api_id, api_secret, sample_device_id)
    try:
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--cloud-worker"],
            input=json.dumps(query, ensure_ascii=True).encode("ascii"), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=CLOUD_TIMEOUT, check=False)
        if result.returncode:
            raise ValueError()
        payload = _strict_json(result.stdout)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ValueError()
        _records(payload.get("devices"))
        return payload["devices"]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError, ValueError, SetupError):
        raise SetupError("No se pudo obtener la lista Cloud dentro del plazo. Revisa región, permisos y vinculación de Tuya IoT.") from None


def _read_file(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_JSON + 1)
        return _records(_strict_json(raw))
    except (OSError, TypeError, ValueError):
        raise SetupError("No se pudo leer el archivo JSON indicado.") from None


def _check_source_destination(source, destination):
    """Preserve the imported JSON even with explicit replacement or aliases."""
    try:
        source_path, destination_path = Path(source), Path(destination)
        if source_path.resolve() == destination_path.resolve():
            raise SetupError("El archivo de origen y el destino deben ser distintos; no se sustituye el JSON importado.")
        if (source_path.exists() and destination_path.exists()
                and source_path.samefile(destination_path)):
            raise SetupError("El archivo de origen y el destino deben ser distintos; no se sustituye el JSON importado.")
    except SetupError:
        raise
    except (OSError, TypeError, ValueError):
        raise SetupError("No se pudo comprobar que las rutas de origen y destino sean distintas.") from None


def _demo_records():
    return _records([
        {"id": "demo_l20_device_001", "key": "0123456789abcdef", "name": "L20 de ejemplo", "mac": _DEMO_MAC},
        {"id": "demo_l20_device_002", "key": "fedcba9876543210", "name": "Segundo L20 de ejemplo", "mac": "02:00:00:23:45:68"},
    ])


def _normalized_mac(value):
    compact = re.sub(r"[:-]", "", value.strip())
    if re.fullmatch(r"[0-9A-Fa-f]{12}", compact) is None:
        return ""
    mac = ":".join(compact[index:index + 2].upper() for index in range(0, 12, 2))
    try:
        validate_credentials({"target_ip": _DEMO_IP, "target_mac": mac,
            "device_id": "format_check", "local_key": "0123456789abcdef"})
        return mac
    except RfError:
        return ""


def run_setup(path, *, from_file=None, replace=False, demo=False):
    """Choose one source/device, confirm local target, then save minimal DPAPI."""
    if demo and from_file is not None:
        raise SetupError("La demostración no admite importar un archivo. Usa setup --demo sin --from-file.")
    if not demo:
        try:
            check_destination(path, replace=replace)
        except CredentialStoreError as error:
            raise SetupError(str(error)) from None
    print("Asistente L20. No realiza escaneo LAN, aprendizaje ni transmisión RF.")
    if demo:
        print("DEMOSTRACIÓN: datos ficticios en memoria; no se leen ni escriben archivos de credenciales.")
    source = "file" if from_file is not None else ""
    if not source:
        print("1. Obtener dispositivos desde Tuya Cloud\n2. Importar un devices.json existente\n3. Introducir los datos manualmente")
        choice = input("Origen de las credenciales [1/2/3]: ").strip()
        source = {"1": "cloud", "2": "file", "3": "manual"}.get(choice, "")
        if not source:
            raise SetupError("Elige una de las tres fuentes indicadas.")
    if source == "cloud":
        print("Prepara un proyecto en Tuya IoT, vincula tu cuenta de la app y autoriza la consulta de dispositivos.")
        print("Necesitas el Access ID, Access Secret, región del centro de datos y un device_id de esa cuenta.")
        if demo:
            records = _demo_records()
        else:
            region = input("Región [cn/us/us-e/eu/eu-w/in/sg]: ").strip().lower()
            if region not in REGIONS:
                raise SetupError("La región debe ser una de las indicadas.")
            records = _records(_cloud_devices(region, _hidden("Access ID (oculto): "),
                _hidden("Access Secret (oculto): "), _hidden("device_id de referencia (oculto): ")))
        candidate = _choose(records)
    elif source == "file":
        if demo:
            records = _demo_records()
        else:
            selected_path = from_file if from_file is not None else input("Ruta del devices.json existente: ").strip()
            _check_source_destination(selected_path, path)
            records = _read_file(selected_path)
        candidate = _choose(records)
    else:
        candidate = _demo_records()[0] if demo else _Candidate("Datos manuales",
            _hidden("device_id (oculto): "), _hidden("local_key de 16 bytes (oculta): "))
    # Reject an unusable selected key/profile before asking for router details.
    try:
        validate_credentials({"target_ip": _DEMO_IP, "target_mac": _DEMO_MAC,
            "device_id": candidate.device_id, "local_key": candidate.local_key,
            "port": candidate.port, "version": candidate.version})
    except RfError:
        raise SetupError("El dispositivo seleccionado necesita una clave local de 16 bytes, Tuya 3.3 y TCP 6668.") from None
    print("Consulta la IP privada y la MAC en tu router. No se utiliza la IP devuelta por la nube.")
    ip_default = _DEMO_IP if demo else ""
    mac_default = _normalized_mac(candidate.mac) if source == "file" or demo else ""
    host = input("IPv4 privada del L20" + (f" [{ip_default}]" if ip_default else "") + ": ").strip() or ip_default
    mac = input("MAC del L20, comprueba el router" + (f" [{mac_default}]" if mac_default else "") + ": ").strip() or mac_default
    value = {"target_ip": host, "target_mac": _normalized_mac(mac),
        "device_id": candidate.device_id, "local_key": candidate.local_key,
        "port": candidate.port, "version": candidate.version}
    try:
        checked = validate_credentials(value)
    except RfError:
        raise SetupError("Revisa la IPv4 privada y la MAC del router; no se guardó ninguna credencial.") from None
    minimal = {"target_ip": checked.target_ip, "target_mac": checked.target_mac,
        "device_id": checked.device_id, "local_key": checked.local_key.decode("latin1"),
        "port": checked.port, "version": checked.version}
    print(f"Destino: {checked.target_ip} · MAC {checked.target_mac} · Tuya 3.3 · TCP 6668")
    print("Dispositivo: " + _masked(checked.device_id))
    if input("¿Guardar esta configuración? [s/N]: ").strip().lower() not in ("s", "si", "sí"):
        print("Configuración cancelada. No se guardó ningún archivo.")
        return
    if demo:
        seal(json.dumps(minimal, ensure_ascii=False).encode("utf-8"))
        print("Demostración terminada: cifrado probado en memoria, sin crear ni sustituir archivos.")
        return
    try:
        write_credentials(path, minimal, replace=replace)
    except CredentialStoreError as error:
        raise SetupError(str(error)) from None
    print("Configuración guardada con Windows DPAPI. La conexión LAN todavía no se ha comprobado.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--cloud-worker"]:
        _cloud_worker()
    else:
        raise SystemExit("Este módulo se utiliza mediante l20.py setup.")
