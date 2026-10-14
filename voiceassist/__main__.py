"""VoiceAssist command-line launch."""

import argparse
import os
from pathlib import Path
import sys

from .cli import run
from .instance import SingleInstance, suppress_error_dialogs
from .platform import current_host
from .speech import run_voice, report_voice_failure
from .startup import StartupManager, WindowsRunRegistry, startup_command


def run_setup(config_dir: Path, model: "Path | None") -> int:
    from .browser import SitesStore
    from .online import OnlineInfo
    from .settings import Settings
    from .setup_wizard import Wizard, input_devices, tts_voices
    from .piper_voice import find_piper

    def save_voice(name: str) -> None:
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "voice.txt").write_text(name, encoding="utf-8")

    autostart = None
    if sys.platform == "win32" and model is not None and model.is_dir():
        manager = StartupManager(WindowsRunRegistry())
        autostart = lambda: manager.install(startup_command(Path(sys.executable), model.resolve(), frozen=getattr(sys, "frozen", False)))
    try:
        Wizard(Settings(config_dir / "settings.json"), microphones=input_devices, voices=tts_voices, save_voice=save_voice,
               find_city=OnlineInfo().find_city, save_site=SitesStore(config_dir / "sites.json").set, autostart=autostart,
               piper_available=find_piper((Path(sys.executable).parent, config_dir)) is not None).run()
    except (EOFError, KeyboardInterrupt):
        print("Настройка прервана. Уже введённое сохранено.")
    except OSError as error:
        print("Не удалось сохранить настройки: {}".format(error), file=sys.stderr)
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="VoiceAssist")
    parser.add_argument("--voice", action="store_true", help="локальное голосовое управление")
    parser.add_argument("--model", type=Path, help="папка распакованной русской модели Vosk")
    parser.add_argument("--set-site", nargs=2, metavar=("NAME", "URL"), help="сохранить адрес сайта")
    parser.add_argument("--register-extension-id", metavar="ID", help="зарегистрировать ID расширения Chrome")
    parser.add_argument("--native-host-exe", type=Path, help="путь к VoiceAssistNativeHost.exe")
    parser.add_argument("--list-tts-voices", action="store_true", help="показать установленные голоса синтеза речи")
    parser.add_argument("--set-tts-voice", metavar="NAME", help="выбрать голос по части названия; пустая строка — автовыбор")
    parser.add_argument("--setup", action="store_true", help="мастер настройки Веги для близкого человека")
    startup = parser.add_mutually_exclusive_group()
    startup.add_argument("--install-autostart", action="store_true", help="включить запуск после входа в Windows")
    startup.add_argument("--remove-autostart", action="store_true", help="отключить автозапуск")
    startup.add_argument("--status-autostart", action="store_true", help="показать состояние автозапуска")
    args = parser.parse_args()
    config_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist"
    if args.setup:
        return run_setup(config_dir, args.model)
    if args.list_tts_voices:
        try:
            import pyttsx3
            from .speech import sapi_russian_voice_ids
            russian = {item.casefold() for item in sapi_russian_voice_ids()}
            for voice in pyttsx3.init().getProperty("voices"):
                print("{}{}".format(voice.name, " (русский)" if str(voice.id).casefold() in russian else ""))
        except Exception as error:
            print("Не удалось получить список голосов: {}".format(error), file=sys.stderr)
            return 3
        return 0
    if args.set_tts_voice is not None:
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "voice.txt").write_text(args.set_tts_voice.strip(), encoding="utf-8")
        except OSError as error:
            print("Не удалось сохранить голос: {}".format(error), file=sys.stderr)
            return 3
        print("Голос сохранён." if args.set_tts_voice.strip() else "Включён автовыбор русского голоса.")
        return 0
    if args.set_site:
        from .browser import SitesStore
        store = SitesStore(Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist" / "sites.json")
        try:
            store.set(args.set_site[0], args.set_site[1])
        except (OSError, ValueError) as error:
            print("Не удалось сохранить сайт: {}".format(error), file=sys.stderr)
            return 2
        print("Сайт сохранён: {}.".format(args.set_site[0]))
        from .browser import site_key
        from .core import speakable_site_name
        if not speakable_site_name(site_key(args.set_site[0])):
            print("Внимание: это название нельзя произнести голосом. Добавьте ещё русское, например: --set-site \"хд резка\" АДРЕС.")
        return 0
    if args.register_extension_id:
        compatibility = current_host()
        if not compatibility.supported:
            print(compatibility.message, file=sys.stderr)
            return 2
        from .bridge_install import BridgeRegistry, register_bridge
        host_exe = args.native_host_exe or Path(sys.executable).parent / "VoiceAssistNativeHost.exe"
        try:
            manifest = register_bridge(args.register_extension_id, host_exe,
                                       Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist", BridgeRegistry())
        except (OSError, ValueError) as error:
            print("Не удалось зарегистрировать расширение: {}".format(error), file=sys.stderr)
            return 3
        print("Связь с расширением зарегистрирована: {}.".format(manifest))
        return 0
    if args.install_autostart or args.remove_autostart or args.status_autostart:
        compatibility = current_host()
        if not compatibility.supported:
            print(compatibility.message, file=sys.stderr)
            return 2
        manager = StartupManager(WindowsRunRegistry())
        if args.status_autostart:
            print("Автозапуск включён." if manager.registry.read() else "Автозапуск выключен.")
            return 0
        if args.remove_autostart:
            success = manager.remove()
            print("Автозапуск выключен." if success else "Не удалось проверить отключение автозапуска.")
            return 0 if success else 3
        if args.model is None or not args.model.is_dir():
            print("Сначала укажите существующую папку модели через --model.", file=sys.stderr)
            return 2
        command = startup_command(Path(sys.executable), args.model.resolve(), frozen=getattr(sys, "frozen", False))
        try:
            success = manager.install(command)
        except (OSError, ValueError) as error:
            print("Не удалось включить автозапуск: {}".format(error), file=sys.stderr)
            return 3
        print("Автозапуск включён." if success else "Не удалось проверить автозапуск.")
        return 0 if success else 3
    if not args.voice:
        return run()
    compatibility = current_host()
    if not compatibility.supported:
        print(compatibility.message, file=sys.stderr)
        return 2
    if args.model is None:
        print("Для голосового режима укажите --model с папкой русской модели Vosk.", file=sys.stderr)
        return 2
    suppress_error_dialogs()
    try:
        if not SingleInstance().acquire():
            print("Помощник уже запущен.", file=sys.stderr)
            report_voice_failure("Второй экземпляр не запущен: Вега уже работает.", config_dir / "last-error.log")
            return 4
    except OSError as error:
        print("Не удалось проверить второй экземпляр: {}".format(error), file=sys.stderr)
    try:
        run_voice(args.model, config_dir=config_dir)
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print("Голосовой режим не готов: {}".format(error), file=sys.stderr)
        report_voice_failure("Голосовой режим не готов: {}: {}".format(type(error).__name__, error), config_dir / "last-error.log")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
