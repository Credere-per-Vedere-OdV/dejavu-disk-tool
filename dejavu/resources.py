"""Resources bundled unchanged in the source package and in the EXE."""
from pathlib import Path
import sys


def asset_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name
