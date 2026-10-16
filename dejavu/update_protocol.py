"""Signed release protocol. No disk backend imports or physical-device access."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PRODUCT = "dejavu-disk-tool"
PLATFORM = "windows-x64"
PAYLOAD = "DejavuDiskTool-Windows-x64.zip"
MANIFEST = "aggiornamento.json"
SIGNATURE = "aggiornamento.sig"
INSTALLER = "DejavuDiskTool-Installazione-Windows-x64.zip"
ENTRY = "DejavuDiskTool.exe"
LAUNCHER_PROTOCOL = 1
MAX_ARCHIVE = 600 * 1024 * 1024
MAX_EXPANDED = 1800 * 1024 * 1024
MAX_FILES = 12000


class UpdateError(RuntimeError):
    pass


def version_key(value):
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-beta(?:\.(0|[1-9]\d*))?)?", value)
    if not match:
        raise UpdateError("Numero di versione non valido.")
    major, minor, patch, beta = match.groups()
    return (int(major), int(minor), int(patch), 0 if "-beta" in value else 1, int(beta or 0))


def valid_repository(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value):
        raise UpdateError("Repository GitHub non valido.")
    if value.split("/")[1] in (".", ".."):
        raise UpdateError("Repository GitHub non valido.")
    return value


def json_object(raw):
    def pairs(items):
        data = {}
        for key, value in items:
            if key in data:
                raise UpdateError("Metadati con campi duplicati.")
            data[key] = value
        return data

    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("costante non valida")))
    except (ValueError, UnicodeError, TypeError) as error:
        raise UpdateError("Metadati JSON non validi.") from error
    if not isinstance(value, dict):
        raise UpdateError("Metadati JSON non validi.")
    return value


def verify_manifest(raw, signature, public_key, repository, expected_version):
    """Authenticate the exact manifest bytes before using any payload metadata."""
    if len(raw) > 65536 or len(signature) > 256:
        raise UpdateError("Metadati troppo grandi.")
    try:
        key = serialization.load_pem_public_key(public_key)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("tipo di chiave inatteso")
        decoded = base64.b64decode(signature.strip(), validate=True)
        key.verify(decoded, raw)
    except (ValueError, TypeError, InvalidSignature) as error:
        raise UpdateError("Firma dell'aggiornamento non valida: versione rifiutata.") from error
    data = json_object(raw)
    if (type(data.get("format")) is not int or data["format"] != 1 or
            data.get("product") != PRODUCT or data.get("platform") != PLATFORM or
            data.get("repository") != repository or data.get("version") != expected_version or
            data.get("artifact") != PAYLOAD or data.get("entrypoint") != ENTRY):
        raise UpdateError("Aggiornamento destinato a un altro programma, repository o versione.")
    version_key(data["version"])
    minimum = data.get("minimum_launcher")
    if type(minimum) is not int or not 1 <= minimum <= LAUNCHER_PROTOCOL:
        raise UpdateError("Questo aggiornamento richiede un avviatore più recente.")
    if type(data.get("size")) is not int or not 0 < data["size"] <= MAX_ARCHIVE:
        raise UpdateError("Dimensione del pacchetto non valida.")
    if not isinstance(data.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"]):
        raise UpdateError("Impronta del pacchetto non valida.")
    return data


def release_candidate(releases, repository, current_version, channel="beta", rejected=()):
    valid_repository(repository)
    if channel not in ("beta", "stable"):
        raise UpdateError("Canale di aggiornamento non valido.")
    current = version_key(current_version)
    candidates = []
    if not isinstance(releases, list):
        raise UpdateError("Elenco delle versioni non valido.")
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") is not False or not item.get("published_at"):
            continue
        tag = item.get("tag_name", "")
        if not isinstance(tag, str) or not tag.startswith("v"):
            continue
        version = tag[1:]
        try:
            order = version_key(version)
        except (UpdateError, TypeError):
            continue
        if version in rejected or order <= current:
            continue
        if channel == "stable" and (item.get("prerelease") is not False or "-beta" in version):
            continue
        assets = item.get("assets", [])
        if not isinstance(assets, list):
            continue
        urls = {}
        duplicated = False
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("name") not in (MANIFEST, SIGNATURE, PAYLOAD):
                continue
            name = asset["name"]
            expected = f"https://github.com/{repository}/releases/download/{tag}/{name}"
            if name in urls or asset.get("browser_download_url") != expected or asset.get("state") != "uploaded":
                duplicated = True
                break
            urls[name] = expected
        if not duplicated and set(urls) == {MANIFEST, SIGNATURE, PAYLOAD}:
            candidates.append((order, version, urls))
    if not candidates:
        return None
    _, version, urls = max(candidates, key=lambda x: x[0])
    return version, urls


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_members(archive):
    """Reject Windows path aliases, traversal, symlinks and excessive expansion."""
    items = archive.infolist()
    if len(items) > MAX_FILES:
        raise UpdateError("Il pacchetto contiene troppi file.")
    total = 0
    seen = set()
    files = set()
    validated = []
    reserved = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
    reserved |= {prefix + str(n) for prefix in ("COM", "LPT") for n in range(1, 10)}
    reserved |= {prefix + n for prefix in ("COM", "LPT") for n in ("¹", "²", "³")}
    for item in items:
        name = item.filename
        if (item.orig_filename != name or not name or "\\" in name or ":" in name or any(ord(c) < 32 for c in name)
                or any(c in name for c in '<>"|?*') or name.startswith("/")):
            raise UpdateError("Il pacchetto contiene un percorso non sicuro.")
        parts = name[:-1].split("/") if name.endswith("/") else name.split("/")
        if any(p in ("", ".", "..") or p.endswith((".", " ")) or
               p.split(".", 1)[0].upper() in reserved for p in parts):
            raise UpdateError("Il pacchetto contiene un percorso Windows ambiguo.")
        if len(name) > 220 or not name.isascii():
            raise UpdateError("Il pacchetto contiene un percorso non supportato.")
        canonical = "/".join(parts).casefold()
        if canonical in seen:
            raise UpdateError("Il pacchetto contiene percorsi duplicati.")
        seen.add(canonical)
        mode = item.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1:
            raise UpdateError("Il pacchetto contiene collegamenti o file speciali.")
        if bool(kind == stat.S_IFDIR) and not item.is_dir():
            raise UpdateError("Tipo di file ZIP ambiguo.")
        if not item.is_dir():
            files.add(canonical)
        total += item.file_size
        if item.file_size < 0 or total > MAX_EXPANDED:
            raise UpdateError("Il pacchetto decompresso è troppo grande.")
        validated.append((item, parts))
    for _, parts in validated:
        if any("/".join(parts[:n]).casefold() in files for n in range(1, len(parts))):
            raise UpdateError("Il pacchetto sovrappone file e cartelle.")
    return validated


def extract_payload(path, destination, cancelled=lambda: False):
    destination = Path(destination)
    destination.mkdir()
    with zipfile.ZipFile(path) as archive:
        members = safe_members(archive)
        for item, parts in members:
            if cancelled():
                raise UpdateError("Aggiornamento annullato.")
            target = destination.joinpath(*parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(item) as source, target.open("xb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    if cancelled():
                        raise UpdateError("Aggiornamento annullato.")
                    written += len(chunk)
                    if written > item.file_size:
                        raise UpdateError("Dimensione decompressa inattesa.")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if written != item.file_size:
                raise UpdateError("Il pacchetto contiene un file incompleto.")


def validate_bundle(folder, version):
    folder = Path(folder)
    version_key(version)
    info = json_object((folder / "versione.json").read_bytes())
    if info != {"version": version, "product": PRODUCT, "platform": PLATFORM}:
        raise UpdateError("La cartella installata non corrisponde alla versione richiesta.")
    executable = folder / ENTRY
    if not executable.is_file() or not (folder / "_internal" / "assets" / "logo_cpv.png").is_file():
        raise UpdateError("La cartella del programma è incompleta.")
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise UpdateError("Il pacchetto non contiene un eseguibile Windows.")
    return executable
