"""Windows-only process coordination and an elevated child whose lifetime is tracked."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess


def enable_dpi_awareness():
    if os.name != "nt":
        return
    try:
        # System-aware avoids Windows bitmap enlargement at the startup monitor.
        # Tk still reports the actual density used for raster asset rendering.
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (OSError, AttributeError):
            pass


class InstanceBusy(RuntimeError):
    pass


class WindowsInstance:
    def __init__(self, name):
        self.name, self.handle = name, None

    def __enter__(self):
        if os.name != "nt":
            return self
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        ctypes.set_last_error(0)
        self.handle = kernel.CreateMutexW(None, True, self.name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(self.handle)
            self.handle = None
            raise InstanceBusy("Dejavu Disk Tool è già aperto in questa sessione Windows.")
        return self

    def __exit__(self, *_):
        if self.handle:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.ReleaseMutex(self.handle)
            kernel.CloseHandle(self.handle)
            self.handle = None


APP_MUTEX = "Local\\CrederePerVedere.DejavuDiskTool.App"
LAUNCHER_MUTEX = "Local\\CrederePerVedere.DejavuDiskTool.Avvio"


def run_elevated_and_wait(executable: Path, arguments, elevate=True):
    """Keep the launcher lock until the actual elevated process has exited."""
    if os.name != "nt":
        raise OSError("Questo avviatore richiede Windows.")

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # NOCLOSEPROCESS | NOASYNC
    info.lpVerb = "runas" if elevate else "open"
    info.lpFile = str(executable)
    info.lpParameters = subprocess.list2cmdline(list(arguments))
    info.lpDirectory = str(executable.parent)
    info.nShow = 1
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_int32
    ole.CoUninitialize.argtypes = []
    hr = ole.CoInitializeEx(None, 0x2 | 0x4)  # STA | DISABLE_OLE1DDE
    if hr not in (0, 1, -2147417850):  # RPC_E_CHANGED_MODE: COM already initialized.
        raise OSError(f"Impossibile inizializzare Windows COM: {hr}.")
    try:
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not info.hProcess:
            raise OSError("Windows non ha restituito il processo da monitorare.")
        try:
            if kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF) != 0:
                raise OSError("Impossibile seguire il processo del programma.")
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value
        finally:
            kernel.CloseHandle(info.hProcess)
    finally:
        if hr in (0, 1):
            ole.CoUninitialize()
