"""CLI local del L20. Solo capture y send contactan con el dispositivo."""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import uuid

import app
from rf_device import MAX_FRAME, Radio, RfError, credential_info, seal, validate_code, validate_credentials


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_code(path):
    """Read Base64 or a complete UTF-8 JSON container, without echoing either."""
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_FRAME:
        raise app.AppError("El archivo de código está vacío o es demasiado grande.")
    text = path.read_text(encoding="utf-8-sig").strip()
    code = base64.b64encode(text.encode("utf-8")).decode("ascii") if text.startswith("{") else text
    return validate_code(code)


def configure(path, replace=False):
    path = Path(path)
    if path.exists() and not replace:
        raise app.AppError("La credencial ya existe. Usa configure --replace para sustituirla.")
    print("Configuración local. No se conecta al L20 ni se verifican las claves por red.")
    value = {"target_ip": input("IPv4 privada del L20: ").strip(),
             "target_mac": input("MAC del L20 (AA:BB:CC:DD:EE:FF): ").strip(),
             "device_id": getpass.getpass("device_id (oculto): "),
             "local_key": getpass.getpass("local_key de 16 bytes (oculta): "),
             "port": 6668, "version": "3.3"}
    checked = validate_credentials(value)
    value["target_ip"], value["target_mac"] = checked.target_ip, checked.target_mac
    encrypted = seal(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / ("." + secrets.token_hex(16) + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Windows rename refuses to overwrite, including a concurrent writer.
            temporary.rename(path)
    finally:
        temporary.unlink(missing_ok=True)
    print("Credencial protegida con DPAPI. Ejecuta info para comprobar su lectura local.")


def metadata(record):
    return {key: record[key] for key in ("id", "name", "revision", "summary", "physical_result")}


def parser_for_cli():
    parser = argparse.ArgumentParser(description="L20 RF LAN: capturar, guardar y transmitir por Tuya 3.3 en Windows")
    parser.add_argument("--credentials", type=Path, default=app.DEFAULT_CREDENTIAL,
                        help="Archivo DPAPI (opción global, antes del subcomando)")
    parser.add_argument("--data", type=Path, help="Carpeta de capturas DPAPI (antes del subcomando)")
    commands = parser.add_subparsers(dest="command", required=True)
    config = commands.add_parser("configure", help="Crear credencial DPAPI mediante preguntas locales")
    config.add_argument("--replace", action="store_true", help="Sustituir una credencial existente")
    commands.add_parser("info", help="Leer configuración local sin contactar con el L20")
    commands.add_parser("list", help="Listar capturas, sin mostrar códigos")
    capture = commands.add_parser("capture", help="Activar aprendizaje y guardar un código recibido")
    capture.add_argument("--name", required=True)
    capture.add_argument("--frequency", choices=("0", "433.92"), default="0")
    capture.add_argument("--seconds", type=int, choices=range(1, 121), default=30, metavar="1..120")
    save = commands.add_parser("save", help="Guardar o editar una captura desde Base64 o JSON v2")
    save.add_argument("--name", required=True)
    save.add_argument("--file", type=Path, required=True)
    save.add_argument("--id", help="UUID existente que se desea editar")
    save.add_argument("--notes", default=None)
    export = commands.add_parser("export", help="Exportar Base64 sensible a un archivo nuevo")
    export.add_argument("id")
    export.add_argument("--output", type=Path, required=True)
    send = commands.add_parser("send", help="Intentar una única orden RF; puede accionar el receptor")
    send.add_argument("id")
    send.add_argument("--times", type=int, choices=range(1, 7), default=1, metavar="1..6")
    validate = commands.add_parser("validate", help="Validar archivo sin dispositivo ni transmisión")
    validate.add_argument("--file", type=Path, required=True)
    web = commands.add_parser("web", help="Abrir interfaz en 127.0.0.1")
    web.add_argument("--port", type=int, default=58745)
    web.add_argument("--demo", action="store_true")
    web.add_argument("--no-browser", action="store_true")
    return parser


def main(argv=None):
    args = parser_for_cli().parse_args(argv)
    if os.name != "nt":
        print("Esta versión necesita Windows para DPAPI y ARP.", file=sys.stderr)
        return 2
    directory = args.data or app.ROOT / "datos" / "capturas"
    library = app.Library(directory)
    try:
        if args.command == "configure":
            configure(args.credentials, args.replace)
        elif args.command == "info":
            info = credential_info(args.credentials)
            emit(info)
            return 0 if info["ready"] else 2
        elif args.command == "validate":
            emit(read_code(args.file)["summary"])
        elif args.command == "list":
            records, unreadable = library.list()
            emit({"captures": records, "unreadable_captures": unreadable})
        elif args.command == "save":
            previous = library.get(args.id) if args.id else {}
            record = library.save({**previous, "name": args.name,
                "notes": args.notes if args.notes is not None else previous.get("notes", ""),
                "code": read_code(args.file)["canonical_code"]})
            emit(metadata(record))
        elif args.command == "export":
            record = library.get(args.id)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="ascii") as stream:
                stream.write(record["code"] + "\n")
            print("Código exportado en texto claro. Trata ese archivo como una credencial de acceso.")
        elif args.command == "capture":
            if not args.name.strip() or len(args.name) > 100:
                raise app.AppError("Escribe un nombre de hasta 100 caracteres antes de capturar.")
            result = Radio(args.credentials).capture(threading.Event(),
                lambda message: print(message, file=sys.stderr), frequency=args.frequency, seconds=args.seconds)
            record = library.save({"name": args.name, "code": result["code"]})
            emit({**metadata(record), "source_dp": result["source_dp"],
                  "learning_exit_sent": result["learning_exit_sent"], "freshness_verified": False})
            if not result["learning_exit_sent"]:
                print("No se confirmó el envío de salida del aprendizaje.", file=sys.stderr)
        elif args.command == "send":
            record = library.get(args.id)
            result = Radio(args.credentials).send(record["code"], times=args.times)
            row = {"id": str(uuid.uuid4()), "at": app.now(), "name": record["name"],
                   "times": args.times, "outcome": result["outcome"], "problem": result["problem"],
                   "frame_write_attempted": result["frame_write_attempted"],
                   "timing_ms": result.get("timing_ms", {}), "physical_result": "unverified", "demo": False}
            try:
                app.TrialLog(directory).append(row)
                result["history_saved"] = True
            except Exception:
                result["history_saved"] = False
            emit({"operation_id": row["id"], **result})
            print("La respuesta LAN no confirma el efecto físico. No hay reintentos automáticos.", file=sys.stderr)
            return 0 if result["outcome"] == "ACKNOWLEDGED" else 3
        elif args.command == "web":
            options = ["--credentials", str(args.credentials), "--port", str(args.port)]
            if args.data:
                options += ["--data", str(args.data)]
            if args.demo:
                options.append("--demo")
            if args.no_browser:
                options.append("--no-browser")
            return app.main(options)
    except KeyboardInterrupt:
        print("Operación interrumpida. No se repetirá ninguna orden.", file=sys.stderr)
        return 130
    except (app.AppError, RfError) as error:
        print(str(error), file=sys.stderr)
        if isinstance(error, RfError) and error.cleanup_sent is False:
            print("No se confirmó el envío de salida del aprendizaje.", file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        print("No se pudo leer o escribir el archivo local. Comprueba ruta, permisos y formato; no se sobrescriben exportaciones.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
