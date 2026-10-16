"""Build the Windows app, stable launcher, and signed update assets centrally."""
from pathlib import Path
import ctypes
import os
import subprocess
import sys
import venv


def main():
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        print("La compilazione richiede Windows e Python a 64 bit.")
        return 2
    root = Path(__file__).resolve().parent
    python = root / ".venv-build" / "Scripts" / "python.exe"
    if not python.exists():
        venv.create(root / ".venv-build", with_pip=True)
    def run(args, signing=False):
        env = os.environ.copy()
        if not signing:
            env.pop("DEJAVU_SIGNING_KEY_PEM", None)
        subprocess.run([str(python), *args], cwd=root, env=env, check=True)
    run(["-m", "pip", "install", "-r", str(root / "requirements-build.txt")])
    run(["-m", "unittest", "discover", "-s", "tests", "-v"])
    run(["-m", "dejavu.release_tools", "prepare-key"], signing=True)
    (root / "build").mkdir(exist_ok=True)
    for name, entry in (("DejavuDiskTool", "main.py"), ("AvviaDejavu", "avvia_dejavu.py")):
        run(["-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
             "--noupx", "--name", name, "--add-data", str(root / "assets") + ":assets",
             "--manifest", str(root / "assets" / "windows.manifest"),
             "--distpath", str(root / "release-build"), "--workpath", str(root / "build" / name),
             "--specpath", str(root / "build"), str(root / entry)])
    run(["-m", "dejavu.release_tools", "package", "--app-dir", str(root / "release-build" / "DejavuDiskTool"),
         "--launcher-dir", str(root / "release-build" / "AvviaDejavu"), "--output", str(root / "release")], signing=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
