"""Write only the selected device's LAN configuration, encrypted with DPAPI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets

from rf_device import seal, validate_credentials


class CredentialStoreError(Exception):
    """Fixed user-facing errors without paths, credential values or raw failures."""


def check_destination(path, replace=False):
    destination = Path(path)
    if destination.is_symlink() or destination.parent.is_symlink():
        raise CredentialStoreError("La ruta de configuración no admite enlaces simbólicos.")
    if destination.exists() and not replace:
        raise CredentialStoreError("La credencial ya existe. Usa --replace para sustituirla.")


def write_credentials(path, value, replace=False):
    """Validate, whitelist and atomically save; never persist Cloud credentials."""
    check_destination(path, replace)
    checked = validate_credentials(value)
    record = {"target_ip": checked.target_ip, "target_mac": checked.target_mac,
              "device_id": checked.device_id, "local_key": checked.local_key.decode("latin1"),
              "port": checked.port, "version": checked.version}
    encrypted = seal(json.dumps(record, ensure_ascii=False).encode("utf-8"))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    check_destination(destination, replace)
    temporary = destination.parent / ("." + secrets.token_hex(16) + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, destination)
        else:
            # Windows rename refuses to overwrite an existing destination.
            temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)
