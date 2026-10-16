"""Build-machine tools. Private signing keys never enter distributable folders."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import __version__
from .update_protocol import (ENTRY, INSTALLER, MANIFEST, PAYLOAD, PLATFORM, PRODUCT,
                              SIGNATURE, file_sha256, json_object, safe_members,
                              validate_bundle, valid_repository, version_key)
from .updater import atomic_json

ROOT = Path(__file__).resolve().parent.parent


def signing_key(root=ROOT):
    supplied = os.environ.get("DEJAVU_SIGNING_KEY_PEM")
    public_path = Path(root) / "assets" / "update_public_key.pem"
    if supplied:
        key = serialization.load_pem_private_key(supplied.encode("ascii"), password=None)
    else:
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
        path = local / "CrederePerVedere" / "DejavuDiskTool" / "chiavi_rilascio" / "aggiornamenti-ed25519.pem"
        if not path.exists():
            if public_path.exists():
                raise ValueError("Manca la chiave privata corrispondente al progetto. Usare il PC di compilazione originale "
                                 "o il segreto DEJAVU_SIGNING_KEY_PEM; non creare un'altra chiave per aggiornare i colleghi.")
            path.parent.mkdir(parents=True, exist_ok=True)
            key = Ed25519PrivateKey.generate()
            raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            print("Creata la chiave privata di rilascio nel profilo Windows del responsabile. Conservarne un backup riservato.")
        else:
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("La chiave di rilascio deve essere Ed25519.")
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    if public_path.exists() and public_path.read_bytes() != public:
        raise ValueError("La chiave privata non corrisponde alla chiave pubblica del programma.")
    public_path.write_bytes(public)
    return key


def zip_tree(folder, destination, include_parent=False):
    folder, destination = Path(folder), Path(destination)
    base = folder.parent if include_parent else folder
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(folder.rglob("*")):
            if file.is_symlink():
                raise ValueError("I pacchetti non devono contenere collegamenti simbolici.")
            if file.is_file():
                archive.write(file, file.relative_to(base).as_posix())
    if not include_parent:
        with zipfile.ZipFile(destination) as archive:
            safe_members(archive)


def package(app_dir, launcher_dir, output, root=ROOT, version=__version__):
    root, app_dir, launcher_dir, output = map(Path, (root, app_dir, launcher_dir, output))
    version_key(version)
    config = json_object((root / "assets" / "aggiornamenti.json").read_bytes())
    repository = valid_repository(config["repository"])
    key = signing_key(root)
    output.mkdir(parents=True, exist_ok=True)
    for name in ("LEGGIMI_PRIMA.md", "GUIDA_MAURO_RINNA.html", "VALIDAZIONE.md", "AGGIORNAMENTI_GITHUB.md", "RAPPORTI_E_RIFERIMENTI.md", "impostazioni.ini"):
        shutil.copy2(root / name, app_dir / name)
    atomic_json(app_dir / "versione.json", {"version": version, "product": PRODUCT, "platform": PLATFORM})
    validate_bundle(app_dir, version)
    payload = output / PAYLOAD
    zip_tree(app_dir, payload)
    manifest = {
        "format": 1, "product": PRODUCT, "platform": PLATFORM, "repository": repository,
        "version": version, "artifact": PAYLOAD, "size": payload.stat().st_size,
        "sha256": file_sha256(payload), "entrypoint": ENTRY, "minimum_launcher": 1,
    }
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (output / MANIFEST).write_bytes(raw)
    (output / SIGNATURE).write_bytes(base64.b64encode(key.sign(raw)) + b"\n")

    installation = output / "DejavuDiskTool"
    if installation.exists():
        shutil.rmtree(installation)
    shutil.copytree(launcher_dir, installation)
    shutil.copytree(app_dir, installation / "versioni" / version)
    shutil.copy2(root / "impostazioni.ini", installation / "impostazioni.ini")
    for name in ("LEGGIMI_PRIMA.md", "GUIDA_MAURO_RINNA.html", "VALIDAZIONE.md", "AGGIORNAMENTI_GITHUB.md", "RAPPORTI_E_RIFERIMENTI.md"):
        shutil.copy2(root / name, installation / name)
    atomic_json(installation / "attiva.json", {"format": 1, "active": version, "previous": None, "rejected": []})
    for name, flags in (("Prova_interfaccia.cmd", "--demo"),
                        ("Rilevamento_senza_cancellazione.cmd", "--diagnostics"),
                        ("Avvia_senza_aggiornamenti.cmd", "--senza-aggiornamenti")):
        (installation / name).write_bytes((f'@echo off\r\nstart "" "%~dp0AvviaDejavu.exe" {flags}\r\n').encode("ascii"))
    zip_tree(installation, output / INSTALLER, include_parent=True)
    print(f"Avvio per i colleghi: {installation / 'AvviaDejavu.exe'}")
    print(f"Prima installazione: {output / INSTALLER}")
    print(f"Release GitHub: {PAYLOAD}, {MANIFEST}, {SIGNATURE} e {INSTALLER}")
    print("Eseguire il collaudo Windows prima di pubblicare la release.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare-key", "package"))
    parser.add_argument("--app-dir", type=Path)
    parser.add_argument("--launcher-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare-key":
        signing_key()
    else:
        if not all((args.app_dir, args.launcher_dir, args.output)):
            parser.error("package richiede --app-dir, --launcher-dir e --output")
        package(args.app_dir, args.launcher_dir, args.output)


if __name__ == "__main__":
    main()
