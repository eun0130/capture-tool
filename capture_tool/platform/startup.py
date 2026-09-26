"""Run at Windows sign-in (HKCU Run key). The backend is injectable for tests."""
from __future__ import annotations

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "CaptureTool"


class RegistryRun:
    def set(self, name: str, value: str) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass

    def get(self, name: str, default=None):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                return winreg.QueryValueEx(k, name)[0]
        except FileNotFoundError:
            return default


def set_enabled(enabled: bool, exe_path: str, backend=None) -> None:
    backend = backend if backend is not None else RegistryRun()
    if enabled:
        backend.set(VALUE, f'"{exe_path}" --tray')
    else:
        backend.delete(VALUE)


def is_enabled(backend=None) -> bool:
    backend = backend if backend is not None else RegistryRun()
    return backend.get(VALUE) is not None
