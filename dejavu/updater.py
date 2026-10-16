"""Install a signed Windows release beside the old one, then switch one pointer."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .update_protocol import (MANIFEST, SIGNATURE, PAYLOAD, UpdateError,
                              extract_payload, file_sha256, json_object,
                              release_candidate, safe_members, validate_bundle,
                              valid_repository, verify_manifest, version_key)


def atomic_json(path, data):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".stato-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def allowed_https(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443)
            or parts.fragment or not (host in ("api.github.com", "github.com")
                or host.endswith(".githubusercontent.com")
                or host.endswith(".blob.core.windows.net"))):
        raise UpdateError("Destinazione dell'aggiornamento non autorizzata.")


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        allowed_https(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


class GitHubHTTP:
    def __init__(self, cancelled=lambda: False):
        self.cancelled = cancelled
        self.opener = build_opener(SafeRedirect())

    def transfer(self, url, output, limit, total_timeout=15, progress=lambda _: None):
        allowed_https(url)
        started = time.monotonic()
        request = Request(url, headers={"User-Agent": "DejavuDiskTool-Updater/1",
                                       "Accept": "application/vnd.github+json" if "api.github.com/" in url
                                                 else "application/octet-stream"})
        downloaded = 0
        with self.opener.open(request, timeout=min(10, total_timeout)) as response:
            allowed_https(response.geturl())
            if response.status != 200:
                raise UpdateError("Download non disponibile.")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > limit):
                raise UpdateError("Il download supera la dimensione consentita.")
            read_chunk = getattr(response, "read1", response.read)
            while True:
                if self.cancelled():
                    raise UpdateError("Aggiornamento annullato.")
                if time.monotonic() - started > total_timeout:
                    raise UpdateError("Tempo massimo del download superato.")
                chunk = read_chunk(64 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > limit:
                    raise UpdateError("Il download supera la dimensione consentita.")
                output.write(chunk)
                progress(downloaded)
        return downloaded

    def get(self, url, limit):
        from io import BytesIO
        output = BytesIO()
        self.transfer(url, output, limit)
        return output.getvalue()

    def download(self, url, path, size, progress=lambda _: None):
        with Path(path).open("xb") as output:
            count = self.transfer(url, output, size, total_timeout=600, progress=progress)
            output.flush()
            os.fsync(output.fileno())
        if count != size:
            raise UpdateError("Download incompleto.")


class UpdateManager:
    def __init__(self, installation, config, public_key, http=None, cancelled=lambda: False):
        self.root = Path(installation).resolve()
        self.repository = valid_repository(config.get("repository"))
        self.channel = config.get("channel", "beta")
        if config.get("format") != 1 or self.channel not in ("beta", "stable"):
            raise UpdateError("Configurazione degli aggiornamenti non valida.")
        self.key = public_key
        self.cancelled = cancelled
        self.http = http if http is not None else GitHubHTTP(cancelled)
        self.pointer = self.root / "attiva.json"

    def state(self):
        raw = self.pointer.read_bytes()
        if len(raw) > 65536:
            raise UpdateError("Stato dell'installazione troppo grande.")
        state = json_object(raw)
        if state.get("format") != 1:
            raise UpdateError("Stato dell'installazione non riconosciuto.")
        version_key(state.get("active", ""))
        if state.get("previous") is not None:
            version_key(state["previous"])
        rejected = state.get("rejected", [])
        if not isinstance(rejected, list) or len(rejected) > 200:
            raise UpdateError("Stato degli aggiornamenti non valido.")
        for version in rejected:
            version_key(version)
        return state

    def current(self):
        state = self.state()
        executable = validate_bundle(self.root / "versioni" / state["active"], state["active"])
        return state["active"], executable

    def check(self):
        state = self.state()
        raw = self.http.get(f"https://api.github.com/repos/{self.repository}/releases?per_page=30", 2 * 1024 * 1024)
        try:
            releases = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise UpdateError("Risposta GitHub non leggibile.") from error
        return release_candidate(releases, self.repository, state["active"], self.channel,
                                 state.get("rejected", ()))

    def install(self, candidate, status=lambda _: None):
        version, urls = candidate
        before = self.state()
        if version_key(version) <= version_key(before["active"]):
            raise UpdateError("La nuova versione non è successiva a quella installata.")
        status("Verifica della firma dell'aggiornamento…")
        raw = self.http.get(urls[MANIFEST], 65536)
        signature = self.http.get(urls[SIGNATURE], 256)
        manifest = verify_manifest(raw, signature, self.key, self.repository, version)
        if self.cancelled():
            raise UpdateError("Aggiornamento annullato.")
        versions = self.root / "versioni"
        versions.mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".scaricamento-", dir=versions))
        try:
            archive = work / PAYLOAD
            status(f"Scaricamento della versione {version}…")
            self.http.download(urls[PAYLOAD], archive, manifest["size"],
                               lambda count: status(f"Scaricamento {version} · {count * 100 // manifest['size']}%"))
            if archive.stat().st_size != manifest["size"] or file_sha256(archive) != manifest["sha256"]:
                raise UpdateError("Il pacchetto scaricato non corrisponde alla firma.")
            import zipfile
            with zipfile.ZipFile(archive) as package:
                expanded = sum(info.file_size for info, _ in safe_members(package))
            if shutil.disk_usage(versions).free < expanded + 16 * 1024 * 1024:
                raise UpdateError("Spazio insufficiente per installare l'aggiornamento.")
            status("Preparazione della nuova versione…")
            staging = work / "programma"
            extract_payload(archive, staging, self.cancelled)
            validate_bundle(staging, version)
            (staging / ".aggiornamento.json").write_bytes(raw)
            (staging / ".aggiornamento.sig").write_bytes(signature)
            if self.cancelled() or self.state() != before:
                raise UpdateError("Aggiornamento annullato o installazione cambiata.")
            target = versions / version
            if target.exists():
                # A crash may leave a complete staged version. Never overwrite
                # or merge a version that might be in use: require intervention.
                raise UpdateError("Questa versione è già presente: controllare l'installazione.")
            staging.rename(target)
            next_state = {**before, "active": version, "previous": before["active"]}
            try:
                atomic_json(self.pointer, next_state)
            except Exception:
                # Old pointer and executable remain valid. The unused completed
                # folder is retained for a technician, never deleted blindly.
                raise
            return validate_bundle(target, version)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def rollback(self, failed_version):
        state = self.state()
        if state["active"] != failed_version or not state.get("previous"):
            return False
        previous = state["previous"]
        validate_bundle(self.root / "versioni" / previous, previous)
        rejected = list(dict.fromkeys([*state.get("rejected", []), failed_version]))[-200:]
        atomic_json(self.pointer, {**state, "active": previous, "previous": None, "rejected": rejected})
        return True


def append_log(path, message):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 1024 * 1024:
        path.replace(path.with_suffix(".precedente.log"))
    with path.open("a", encoding="utf-8") as stream:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        stream.write(f"{stamp} {message}\n")
