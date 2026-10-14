"""Accessible text-mode diagnostic entry point."""

import os
from pathlib import Path
import sys
from typing import TextIO

from .core import Assistant
from .platform import current_host


def run(output: TextIO = sys.stdout, check_platform: bool = True, web=None) -> int:
    if check_platform:
        compatibility = current_host()
        if not compatibility.supported:
            print(compatibility.message, file=output)
            return 2
    if web is None and check_platform:
        from .browser_commands import start_web
        web = start_web(Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist")
    assistant = Assistant(web=web)
    print("Вега готова к текстовым командам. Введите 'выход' для завершения.", file=output)
    while True:
        try:
            phrase = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("Работа завершена.", file=output)
            return 0
        if phrase.strip().lower() == "выход":
            print("Работа завершена.", file=output)
            return 0
        answer = assistant.handle(phrase)
        if answer.message:
            print(answer.message, file=output)


if __name__ == "__main__":
    raise SystemExit(run())
