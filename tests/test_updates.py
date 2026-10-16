"""Hostile/corrupt update packages, authenticity, and non-destructive switching."""
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dejavu import update_protocol as protocol
from dejavu.update_protocol import (ENTRY, INSTALLER, MANIFEST, PAYLOAD, PLATFORM, PRODUCT,
                                    SIGNATURE, UpdateError, extract_payload,
                                    release_candidate, safe_members, verify_manifest,
                                    version_key)
from dejavu.updater import UpdateManager, allowed_https, atomic_json

REPO = "Credere-per-Vedere-OdV/dejavu-disk-tool"
OLD = "0.5.0-beta"
NEW = "0.5.1-beta"


def make_bundle(folder, version):
    folder.mkdir(parents=True)
    (folder / ENTRY).write_bytes(b"MZ simulation, not an executable")
    (folder / "_internal" / "assets").mkdir(parents=True)
    (folder / "_internal" / "assets" / "logo_cpv.png").write_bytes(b"simulated image")
    (folder / "versione.json").write_text(json.dumps({"version": version, "product": PRODUCT, "platform": PLATFORM}))


def payload_bytes(version=NEW, extra=()):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(ENTRY, b"MZ fake NEW binary, never executed")
        archive.writestr("_internal/assets/logo_cpv.png", b"simulated image")
        archive.writestr("versione.json", json.dumps({"version": version, "product": PRODUCT, "platform": PLATFORM}))
        for name, data in extra:
            archive.writestr(name, data)
    return stream.getvalue()


def metadata(payload, version=NEW):
    return {"format": 1, "product": PRODUCT, "platform": PLATFORM, "repository": REPO,
            "version": version, "artifact": PAYLOAD, "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(), "entrypoint": ENTRY, "minimum_launcher": 1}


def signed(data, key):
    raw = json.dumps(data).encode()
    return raw, base64.b64encode(key.sign(raw))


def public(key):
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def release(version=NEW, **overrides):
    item = {"tag_name": "v" + version, "draft": False, "prerelease": "-beta" in version,
            "published_at": "2026-10-16T10:00:00Z", "assets": [
                {"name": name, "state": "uploaded", "browser_download_url":
                    f"https://github.com/{REPO}/releases/download/v{version}/{name}"}
                for name in (MANIFEST, SIGNATURE, PAYLOAD)]}
    item.update(overrides)
    return item


class FakeHTTP:
    def __init__(self, payload, raw, signature, releases=None):
        self.payload, self.raw, self.signature = payload, raw, signature
        self.releases = [release()] if releases is None else releases
        self.downloads = 0
        self.after_download = lambda: None

    def get(self, url, limit):
        if "api.github.com" in url:
            result = json.dumps(self.releases).encode()
        else:
            result = self.raw if url.endswith(MANIFEST) else self.signature
        if len(result) > limit:
            raise UpdateError("too big")
        return result

    def download(self, url, path, size, progress):
        self.downloads += 1
        Path(path).write_bytes(self.payload)
        progress(len(self.payload))
        self.after_download()


class AuthenticityTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.data = metadata(payload_bytes())

    def verify(self, data=None, key=None):
        raw, signature = signed(self.data if data is None else data, self.key if key is None else key)
        return verify_manifest(raw, signature, public(self.key), REPO, NEW)

    def test_authentic_manifest_and_tampering(self):
        self.assertEqual(self.verify(), self.data)
        raw, signature = signed(self.data, self.key)
        for changed_raw, changed_sig in ((raw + b" ", signature), (raw, b"not-base64"), (raw, signature[:-4])):
            with self.subTest(signature=changed_sig[:8]):
                with self.assertRaises(UpdateError):
                    verify_manifest(changed_raw, changed_sig, public(self.key), REPO, NEW)

    def test_a_different_signing_key_is_rejected(self):
        with self.assertRaises(UpdateError):
            self.verify(key=Ed25519PrivateKey.generate())

    def test_authenticated_but_wrong_product_or_target_is_rejected(self):
        for field, value in (("product", "another-tool"), ("platform", "linux"), ("repository", "someone/repo"),
                             ("version", OLD), ("artifact", "evil.exe"), ("entrypoint", "../evil.exe")):
            with self.subTest(field=field), self.assertRaises(UpdateError):
                self.verify({**self.data, field: value})

    def test_size_hash_and_launcher_requirements_are_enforced(self):
        for field, value in (("size", True), ("size", -1), ("size", protocol.MAX_ARCHIVE + 1),
                             ("sha256", "bad"), ("minimum_launcher", 2), ("format", True)):
            with self.subTest(field=field, value=value), self.assertRaises(UpdateError):
                self.verify({**self.data, field: value})

    def test_signed_duplicate_json_keys_are_rejected(self):
        raw, _ = signed(self.data, self.key)
        raw = raw[:-1] + b',"version":"0.5.1-beta"}'
        with self.assertRaises(UpdateError):
            verify_manifest(raw, base64.b64encode(self.key.sign(raw)), public(self.key), REPO, NEW)

    def test_version_order_beta_stable_and_malformed(self):
        self.assertLess(version_key("0.5.0-beta"), version_key("0.5.0-beta.2"))
        self.assertLess(version_key("0.5.0-beta.2"), version_key("0.5.0"))
        self.assertLess(version_key("0.9.9"), version_key("0.10.0-beta"))
        for value in ("../x", "1.2", "1.2.3-evil", "01.2.3", "1.2.3/bad"):
            with self.subTest(value=value), self.assertRaises(UpdateError):
                version_key(value)

    def test_drafts_unpublished_old_and_rejected_versions_are_not_installed(self):
        items = [release(OLD), release("0.4.0"), release("0.8.0", draft=True),
                 release("0.9.0", published_at=None), release(NEW)]
        self.assertEqual(release_candidate(items, REPO, OLD)[0], NEW)
        self.assertIsNone(release_candidate(items, REPO, OLD, rejected=[NEW]))

    def test_stable_channel_does_not_receive_beta(self):
        self.assertIsNone(release_candidate([release()], REPO, OLD, channel="stable"))
        self.assertEqual(release_candidate([release(), release("0.5.1")], REPO, OLD, channel="stable")[0], "0.5.1")

    def test_asset_host_path_duplicates_and_incomplete_release_are_rejected(self):
        for url in ("https://evil.example/file.zip", f"https://github.com/elsewhere/tool/releases/download/v{NEW}/{PAYLOAD}",
                    f"http://github.com/{REPO}/releases/download/v{NEW}/{PAYLOAD}"):
            item = release()
            item["assets"][-1]["browser_download_url"] = url
            self.assertIsNone(release_candidate([item], REPO, OLD))
        item = release(); item["assets"].append(deepcopy(item["assets"][0]))
        self.assertIsNone(release_candidate([item], REPO, OLD))
        self.assertIsNone(release_candidate([release(assets=[])], REPO, OLD))

    def test_redirects_require_https_and_github_distribution_hosts(self):
        for url in ("http://github.com/a", "https://github.com.evil.test/a", "file:///C:/file",
                    "https://user:secret@github.com/a", "https://github.com:444/a"):
            with self.subTest(url=url), self.assertRaises(UpdateError):
                allowed_https(url)
        allowed_https("https://release-assets.githubusercontent.com/some/asset?signature=example")


class ArchiveTests(unittest.TestCase):
    def test_traversal_windows_aliases_and_case_collisions_never_extract(self):
        names = ("../outside", "/absolute", "C:/file", "folder\\file", "file:stream", "folder//file",
                 "folder/./file", "folder/trailing.", "NUL.txt", "COM1", "folder/trailing ", "bad?.exe")
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                archive = Path(temp) / "test.zip"
                archive.write_bytes(payload_bytes(extra=[(name, b"x")]))
                with self.assertRaises(UpdateError):
                    extract_payload(archive, Path(temp) / "staging")
                self.assertEqual(list((Path(temp) / "staging").iterdir()), [])
                self.assertFalse((Path(temp) / "outside").exists())
        data = BytesIO(payload_bytes(extra=[("dejavudisktool.EXE", b"x")]))
        with zipfile.ZipFile(data) as archive, self.assertRaises(UpdateError):
            safe_members(archive)

    def test_zip_symlink_is_rejected(self):
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            item = zipfile.ZipInfo("link")
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, "../outside")
        with zipfile.ZipFile(BytesIO(stream.getvalue())) as archive, self.assertRaises(UpdateError):
            safe_members(archive)

    def test_expansion_limit_and_file_directory_overlap_are_rejected(self):
        with zipfile.ZipFile(BytesIO(payload_bytes())) as archive, patch.object(protocol, "MAX_EXPANDED", 1):
            with self.assertRaises(UpdateError):
                safe_members(archive)
        with zipfile.ZipFile(BytesIO(payload_bytes(extra=[("_internal", b"file")])) ) as archive:
            with self.assertRaises(UpdateError):
                safe_members(archive)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_bundle(self.root / "versioni" / OLD, OLD)
        self.original = (self.root / "versioni" / OLD / ENTRY).read_bytes()
        self.state = {"format": 1, "active": OLD, "previous": None, "rejected": []}
        atomic_json(self.root / "attiva.json", self.state)
        (self.root / "impostazioni.ini").write_text("personal settings")
        (self.root / "rapporto.json").write_text("private report")
        self.key = Ed25519PrivateKey.generate()
        self.http = self.make_http()
        self.manager = UpdateManager(self.root, {"format": 1, "repository": REPO, "channel": "beta"},
                                     public(self.key), self.http)

    def tearDown(self):
        self.temp.cleanup()

    def make_http(self, payload=None):
        payload = payload_bytes() if payload is None else payload
        raw, signature = signed(metadata(payload), self.key)
        return FakeHTTP(payload, raw, signature)

    def assert_old_preserved(self):
        self.assertEqual((self.root / "versioni" / OLD / ENTRY).read_bytes(), self.original)
        self.assertEqual((self.root / "impostazioni.ini").read_text(), "personal settings")
        self.assertEqual((self.root / "rapporto.json").read_text(), "private report")
        self.assertFalse(list((self.root / "versioni").glob(".scaricamento-*")))

    def test_signed_update_switches_atomically_without_modifying_old_data(self):
        candidate = self.manager.check()
        result = self.manager.install(candidate)
        self.assertEqual(result, self.root / "versioni" / NEW / ENTRY)
        self.assertEqual(self.manager.current(), (NEW, result))
        self.assertEqual(self.manager.state()["previous"], OLD)
        self.assert_old_preserved()

    def test_bad_signature_stops_before_downloading_executable(self):
        self.http.signature = b"bad signature"
        with self.assertRaises(UpdateError):
            self.manager.install(self.manager.check())
        self.assertEqual(self.http.downloads, 0)
        self.assertEqual(self.manager.state(), self.state)
        self.assert_old_preserved()

    def test_corrupt_or_truncated_payload_keeps_active_version(self):
        for changed in (b"corrupted", self.http.payload[:-1]):
            with self.subTest(length=len(changed)):
                original = self.http.payload
                self.http.payload = changed
                with self.assertRaises(UpdateError):
                    self.manager.install(self.manager.check())
                self.http.payload = original
                self.assertEqual(self.manager.state(), self.state)
                self.assert_old_preserved()

    def test_valid_signature_does_not_allow_unsafe_zip(self):
        self.manager.http = self.make_http(payload_bytes(extra=[("../outside", b"bad")]))
        with self.assertRaises(UpdateError):
            self.manager.install(self.manager.check())
        self.assertEqual(self.manager.state(), self.state)
        self.assert_old_preserved()

    def test_mismatched_version_inside_bundle_is_rejected(self):
        self.manager.http = self.make_http(payload_bytes(version="0.8.0"))
        with self.assertRaises(UpdateError):
            self.manager.install(self.manager.check())
        self.assertEqual(self.manager.state(), self.state)
        self.assert_old_preserved()

    def test_existing_version_is_never_overwritten(self):
        make_bundle(self.root / "versioni" / NEW, NEW)
        previous = (self.root / "versioni" / NEW / ENTRY).read_bytes()
        with self.assertRaises(UpdateError):
            self.manager.install(self.manager.check())
        self.assertEqual((self.root / "versioni" / NEW / ENTRY).read_bytes(), previous)
        self.assertEqual(self.manager.state(), self.state)
        self.assert_old_preserved()

    def test_pointer_write_failure_leaves_previous_version_usable(self):
        with patch("dejavu.updater.atomic_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.manager.install(self.manager.check())
        self.assertEqual(self.manager.current()[0], OLD)
        self.assert_old_preserved()

    def test_cancellation_after_download_never_switches_active_version(self):
        cancelled = [False]
        self.manager.cancelled = lambda: cancelled[0]
        self.http.after_download = lambda: cancelled.__setitem__(0, True)
        with self.assertRaises(UpdateError):
            self.manager.install(self.manager.check())
        self.assertEqual(self.manager.state(), self.state)
        self.assert_old_preserved()

    def test_settings_pointer_changed_during_download_prevents_commit(self):
        self.http.after_download = lambda: atomic_json(self.root / "attiva.json", {**self.state, "rejected": ["0.5.2"]})
        with self.assertRaises(UpdateError):
            self.manager.install(self.manager.check())
        self.assertEqual(self.manager.current()[0], OLD)
        self.assert_old_preserved()

    def test_failed_new_app_rolls_back_and_is_not_downloaded_again(self):
        self.manager.install(self.manager.check())
        self.assertTrue(self.manager.rollback(NEW))
        self.assertEqual(self.manager.current()[0], OLD)
        self.assertIsNone(self.manager.check())
        self.assertIn(NEW, self.manager.state()["rejected"])
        self.assert_old_preserved()

    def test_network_failure_does_not_modify_installation(self):
        with patch.object(self.http, "get", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                self.manager.check()
        self.assertEqual(self.manager.current()[0], OLD)
        self.assert_old_preserved()


class ReleasePackageTests(unittest.TestCase):
    def test_built_assets_verify_and_private_key_is_not_in_any_package(self):
        from dejavu.release_tools import package
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "assets").mkdir()
            (root / "assets" / "aggiornamenti.json").write_text(json.dumps({"format": 1, "repository": REPO, "channel": "beta"}))
            for name in ("LEGGIMI_PRIMA.md", "GUIDA_MAURO_RINNA.html", "VALIDAZIONE.md", "AGGIORNAMENTI_GITHUB.md", "RAPPORTI_E_RIFERIMENTI.md", "impostazioni.ini"):
                (root / name).write_text("test " + name)
            app, launcher, output = root / "app", root / "launcher", root / "output"
            make_bundle(app, OLD)
            launcher.mkdir(); (launcher / "AvviaDejavu.exe").write_bytes(b"MZ fake launcher")
            key = Ed25519PrivateKey.generate()
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
            with patch.dict(os.environ, {"DEJAVU_SIGNING_KEY_PEM": pem.decode()}):
                package(app, launcher, output, root=root, version=OLD)
            verified = verify_manifest((output / MANIFEST).read_bytes(), (output / SIGNATURE).read_bytes(),
                                       public(key), REPO, OLD)
            self.assertEqual(verified["sha256"], hashlib.sha256((output / PAYLOAD).read_bytes()).hexdigest())
            for name in (PAYLOAD, INSTALLER):
                with zipfile.ZipFile(output / name) as archive:
                    for item in archive.infolist():
                        content = archive.read(item)
                        self.assertNotIn(b"BEGIN PRIVATE KEY", content)
                        self.assertNotIn(pem, content)
                    if name == INSTALLER:
                        self.assertIn(f"DejavuDiskTool/versioni/{OLD}/{ENTRY}", archive.namelist())
                        self.assertIn("DejavuDiskTool/AvviaDejavu.exe", archive.namelist())

    def test_build_refuses_different_private_key_for_existing_public_key(self):
        from dejavu.release_tools import signing_key
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "assets").mkdir()
            (root / "assets" / "update_public_key.pem").write_bytes(public(Ed25519PrivateKey.generate()))
            wrong = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            with patch.dict(os.environ, {"DEJAVU_SIGNING_KEY_PEM": wrong.decode()}), self.assertRaises(ValueError):
                signing_key(root)


if __name__ == "__main__":
    unittest.main()
