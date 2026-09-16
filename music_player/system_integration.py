from __future__ import annotations

import subprocess
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "LanMusicPlayer"

APP_USER_MODEL_ID = "Codex.MetalMusicPlayer.1"
APP_DISPLAY_NAME = "Metal Music Player"


def register_app_identity() -> None:
    """Register a friendly name + icon for the AppUserModelID so Windows
    toast notifications show "Metal Music Player" instead of the raw ID."""
    icon = Path(__file__).parent / "icon.ico"
    key_path = rf"Software\Classes\AppUserModelId\{APP_USER_MODEL_ID}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_DISPLAY_NAME)
        if icon.exists():
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon))


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, build_launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                return


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return str(value).strip() == build_launch_command()


def build_launch_command() -> str:
    python_executable = _preferred_python_executable()
    script_path = _entry_script_path()
    return f'"{python_executable}" "{script_path}"'


def shutdown_windows() -> None:
    subprocess.Popen(["shutdown", "/s", "/t", "0"], close_fds=True)


def sleep_windows() -> None:
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], close_fds=True)


def _preferred_python_executable() -> Path:
    executable = Path(sys.executable).resolve()
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.exists():
        return pythonw
    return executable


def _entry_script_path() -> Path:
    argv_path = Path(sys.argv[0]).resolve()
    if argv_path.exists() and argv_path.suffix.lower() in {".py", ".pyw"}:
        return argv_path
    return Path(__file__).resolve().parents[1] / "app.pyw"
