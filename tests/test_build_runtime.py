"""A Windows extension must not depend on Python installed on the build PC."""
from pathlib import Path
import struct
import tempfile
import unittest

from dejavu.build_runtime import check_bundle_python_dlls, pe_dependencies, stable_abi_dlls


def pe_file(*imports, forward=None, machine=0x8664):
    data = bytearray(4096)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, machine, 0)
    struct.pack_into("<H", data, 0x94, 240)
    struct.pack_into("<H", data, 0x98, 0x20B)
    directory = 0x98 + 112
    if imports:
        struct.pack_into("<II", data, directory + 8, 0x200, (len(imports) + 1) * 20)
        for index, name in enumerate(imports):
            pointer = 0x500 + index * 80
            encoded = name.encode() + b"\0"
            data[pointer:pointer + len(encoded)] = encoded
            struct.pack_into("<IIIII", data, 0x200 + index * 20, 1, 0, 0, pointer, 1)
    if forward:
        struct.pack_into("<II", data, directory, 0x800, 0x100)
        struct.pack_into("<I", data, 0x800 + 20, 1)
        struct.pack_into("<I", data, 0x800 + 28, 0x840)
        struct.pack_into("<I", data, 0x840, 0x850)
        encoded = forward.encode() + b"\0"
        data[0x850:0x850 + len(encoded)] = encoded
    return bytes(data)


class WindowsRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_missing_python3t_is_detected_before_packaging(self):
        internal = self.root / "_internal"
        bindings = internal / "cryptography" / "hazmat" / "bindings"
        bindings.mkdir(parents=True)
        (internal / "python315.dll").write_bytes(pe_file())
        (bindings / "_rust.pyd").write_bytes(pe_file("python3t.dll", "KERNEL32.dll"))
        with self.assertRaisesRegex(ValueError, "python3t.dll"):
            check_bundle_python_dlls(self.root)
        (internal / "python3t.dll").write_bytes(pe_file(forward="python315.Py_IncRef"))
        check_bundle_python_dlls(self.root)

    def test_gil_compatibility_shim_is_chosen_instead_of_freethreaded_shim(self):
        (self.root / "python315.dll").write_bytes(pe_file())
        (self.root / "python3t.dll").write_bytes(pe_file(forward="python315t.Py_IncRef"))
        compat = self.root / "abi3t_compat"
        compat.mkdir()
        expected = compat / "python3t.dll"
        expected.write_bytes(pe_file(forward="python315.Py_IncRef"))
        self.assertEqual(stable_abi_dlls(self.root, "python315.dll"), [expected])

    def test_normal_layout_collects_both_matching_stable_abi_dlls(self):
        (self.root / "python315.dll").write_bytes(pe_file())
        files = [self.root / name for name in ("python3.dll", "python3t.dll")]
        for file in files:
            file.write_bytes(pe_file(forward="python315.Py_IncRef"))
        self.assertEqual(stable_abi_dlls(self.root, "python315.dll"), files)

    def test_non_x64_runtime_is_rejected(self):
        (self.root / "python315.dll").write_bytes(pe_file(machine=0xAA64))
        with self.assertRaisesRegex(ValueError, "x64"):
            stable_abi_dlls(self.root, "python315.dll")

    def test_truncated_pe_is_rejected(self):
        for value in (b"", b"MZ", pe_file("python3t.dll")[:0x210]):
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                pe_dependencies(value)
