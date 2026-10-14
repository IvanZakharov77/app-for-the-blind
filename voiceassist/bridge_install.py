"""Per-user registration for the optional Chrome Native Messaging host."""

import json
from pathlib import Path
import re


HOST_NAME = "com.voiceassist.bridge"
REGISTRY_KEY = r"Software\Google\Chrome\NativeMessagingHosts\com.voiceassist.bridge"


class BridgeRegistry:
    def write(self, manifest_path: str) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest_path)

    def read(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                return winreg.QueryValueEx(key, "")[0]
        except FileNotFoundError:
            return None


def register_bridge(extension_id: str, host_exe: Path, config_dir: Path, registry) -> Path:
    if not re.fullmatch("[a-p]{32}", extension_id):
        raise ValueError("Нужен 32-символьный ID расширения Chrome.")
    host_exe = host_exe.resolve(strict=True)
    if not host_exe.is_file():
        raise ValueError("Не найден Native Messaging host.")
    config_dir.mkdir(parents=True, exist_ok=True)
    manifest = config_dir / "native-host.json"
    payload = {"name": HOST_NAME, "description": "VoiceAssist browser bridge",
               "path": str(host_exe), "type": "stdio",
               "allowed_origins": ["chrome-extension://{}/".format(extension_id)]}
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (config_dir / "extension-id.txt").write_text(extension_id, encoding="ascii")
    registry.write(str(manifest))
    if registry.read() != str(manifest):
        raise OSError("Не удалось проверить регистрацию Native Messaging host.")
    return manifest
