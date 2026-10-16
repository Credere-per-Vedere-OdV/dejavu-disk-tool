"""One-time local dependency preparation for the optional Python source launchers."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import venv


def main():
    root = Path(__file__).resolve().parent
    folder = root / ".venv-sorgenti"
    python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.create(folder, with_pip=True)
    requirements = root / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = folder / ".dipendenze-dejavu"
    if not marker.exists() or marker.read_text() != fingerprint:
        print("Preparazione delle dipendenze dei sorgenti. Questo passaggio non serve sui PC con l'EXE.")
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], cwd=root, check=True)
        marker.write_text(fingerprint)
    return subprocess.run([str(python), str(root / "main.py"), *sys.argv[1:]], cwd=root).returncode


if __name__ == "__main__":
    raise SystemExit(main())
