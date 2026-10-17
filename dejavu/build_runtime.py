"""Build-only checks for Python ABI DLLs in standalone Windows bundles."""
from pathlib import Path
import re
import struct


PYTHON_DLL = re.compile(r"python3(?:t|\d+t?)?\.dll", re.IGNORECASE)


def pe_dependencies(data):
    """Return imported DLLs and forwarded-export DLLs without loading code."""
    try:
        if data[:2] != b"MZ":
            raise ValueError("Intestazione Windows mancante.")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("Intestazione PE mancante.")
        machine, count = struct.unpack_from("<HH", data, pe + 4)
        optional_size = struct.unpack_from("<H", data, pe + 20)[0]
        optional = pe + 24
        magic = struct.unpack_from("<H", data, optional)[0]
        if magic not in (0x10B, 0x20B):
            raise ValueError("Formato PE non supportato.")
        directory = optional + (112 if magic == 0x20B else 96)
        sections = []
        for index in range(count):
            start = optional + optional_size + index * 40
            size, address, raw_size, pointer = struct.unpack_from("<IIII", data, start + 8)
            sections.append((address, max(size, raw_size), pointer))

        def offset(rva):
            for address, size, pointer in sections:
                if address <= rva < address + size:
                    return pointer + rva - address
            if 0 <= rva < len(data):
                return rva
            raise ValueError("Indirizzo PE non valido.")

        def string(rva):
            start = offset(rva)
            return data[start:data.index(b"\0", start)].decode("ascii").lower()

        dependencies = set()
        imports, _ = struct.unpack_from("<II", data, directory + 8)
        if imports:
            position = offset(imports)
            while True:
                descriptor = struct.unpack_from("<IIIII", data, position)
                if not any(descriptor):
                    break
                dependencies.add(string(descriptor[3]))
                position += 20
        exports, export_size = struct.unpack_from("<II", data, directory)
        if exports:
            table = offset(exports)
            functions = struct.unpack_from("<I", data, table + 20)[0]
            addresses = offset(struct.unpack_from("<I", data, table + 28)[0])
            if functions > len(data) // 4:
                raise ValueError("Tabella PE non valida.")
            for index in range(functions):
                address = struct.unpack_from("<I", data, addresses + index * 4)[0]
                if exports <= address < exports + export_size:
                    module = string(address).rsplit(".", 1)[0]
                    dependencies.add(module if module.endswith(".dll") else module + ".dll")
        return machine, dependencies
    except (struct.error, IndexError, UnicodeError) as error:
        raise ValueError("File Windows troncato o non valido.") from error


def stable_abi_dlls(base_prefix, runtime_name):
    """Choose shims for this interpreter, including Python 3.15 abi3t compat."""
    base = Path(base_prefix)
    runtime_name = str(runtime_name).lower()
    if not PYTHON_DLL.fullmatch(runtime_name):
        raise ValueError("Nome del runtime Python non riconosciuto.")
    machine, _ = pe_dependencies((base / runtime_name).read_bytes())
    if machine != 0x8664:
        raise ValueError("La distribuzione richiede Python Windows x64.")
    directories = [base / "abi3t-compat", base / "abi3t_compat", base, base / "DLLs"]
    found = []
    for name in ("python3.dll", "python3t.dll"):
        for directory in directories:
            file = directory / name
            if not file.is_file():
                continue
            target_machine, dependencies = pe_dependencies(file.read_bytes())
            if target_machine == machine and runtime_name in dependencies:
                found.append(file)
                break
    return found


def check_bundle_python_dlls(bundle):
    """Fail the build if a packaged extension needs an absent Python DLL."""
    internal = Path(bundle) / "_internal"
    available = {file.name.lower() for file in internal.iterdir() if file.is_file()}
    missing = []
    for file in internal.rglob("*"):
        if file.is_file() and file.suffix.lower() in (".dll", ".pyd"):
            _, dependencies = pe_dependencies(file.read_bytes())
            for dependency in sorted(dependencies):
                if PYTHON_DLL.fullmatch(dependency) and dependency not in available:
                    missing.append(f"{file.relative_to(internal)} richiede {dependency}")
    if missing:
        raise ValueError("Pacchetto Windows incompleto: " + "; ".join(missing))
