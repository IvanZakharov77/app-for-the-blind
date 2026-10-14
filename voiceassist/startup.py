"""Per-user Windows logon startup with readback verification."""

from pathlib import Path
import subprocess


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "VoiceAssist"


def startup_command(executable: Path, model: Path, frozen: bool = False) -> str:
    if frozen:
        arguments = [str(executable), "--voice", "--model", str(model)]
    else:
        arguments = [str(executable), str(Path(__file__).resolve().parent.parent / "run_voiceassist.py"), "--voice", "--model", str(model)]
    return subprocess.list2cmdline(arguments)


class WindowsRunRegistry:
    def read(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return winreg.QueryValueEx(key, VALUE_NAME)[0]
        except FileNotFoundError:
            return None

    def write(self, value: str) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, value)

    def delete(self) -> None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass


class StartupManager:
    def __init__(self, registry):
        self.registry = registry

    def install(self, command: str) -> bool:
        if len(command) > 260:
            raise ValueError("Путь автозапуска длиннее 260 символов.")
        self.registry.write(command)
        return self.registry.read() == command

    def remove(self) -> bool:
        self.registry.delete()
        return self.registry.read() is None
