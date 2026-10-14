"""«Что ты умеешь» answers with a short list of categories; «категория флешки» reads the commands of one.

Ivan, 2026-10-14: all commands at once confuse a person, so Vega offers categories first. Any command
still works directly, without choosing a category. Each category is at most eight commands, said the
way the person would say them.
"""

import re
from typing import Optional, Sequence, Tuple

from .numbers import parse_index

# (spoken name, word stems that name it, commands)
CATEGORIES: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("время и напоминания", ("врем", "час", "напомин", "будильн", "таймер", "заметк", "дат"),
     ("Который час", "Какое сегодня число", "Поставь таймер на пять минут", "Поставь будильник на семь утра",
      "Напомни через десять минут выключить плиту", "Какие напоминания", "Запиши заметку купить хлеб", "Прочитай заметки")),
    ("погода и новости", ("погод", "новост"),
     ("Какая погода", "Погода на завтра", "Какие новости", "Местные новости", "Прочитай новость номер два")),
    ("папки и файлы", ("папк", "файл", "документ", "загрузк"),
     ("Открой загрузки, или документы, или рабочий стол", "Открой мой компьютер", "Что в папке", "Открой номер два",
      "Выйди из папки", "Найди фотографии", "Создай папку Рецепты", "Удали файл черновик")),
    ("флешки и диски", ("флеш", "диск", "накопит", "копир"),
     ("Какие флешки подключены", "Что на флешке", "Сколько места на флешке", "Скопируй второй на флешку",
      "Безопасно извлеки флешку", "Что на диске", "Запиши на диск папку Фото")),
    ("интернет и видео", ("интернет", "сайт", "видео", "ютуб", "браузер", "хром", "фильм", "кино"),
     ("Открой ютуб", "Открой кинокрад, или резку, или филмикс", "Найди в интернете рецепт борща",
      "Найди на ютубе песни Высоцкого", "Что нашлось", "Включи номер два", "Пауза", "Закрой хром")),
    ("компьютер и окна", ("компьютер", "окн", "программ", "громкост", "звук", "батаре", "выключ"),
     ("Громче, или тише", "Какой заряд батареи", "Есть ли интернет", "Открой блокнот", "Какие окна открыты",
      "Закрой окно", "Выключи компьютер")),
    ("голос Веги", ("голос", "реч", "говор", "скорост"),
     ("Говори медленнее, или быстрее", "Голос громче, или тише", "Повтори", "Стоп")),
    ("счёт", ("счет", "счёт", "посчита", "вычисл", "единиц", "математ"),
     ("Сколько будет двенадцать плюс семь", "Переведи пять километров в метры")),
    ("текст и клавиши", ("текст", "клавиш", "печат", "меню", "поле"),
     ("Напиши привет", "Прочитай поле", "Следующий пункт", "Нажми ввод", "Открой меню")),
)

CATEGORY_PHRASE = re.compile(r"(?:категория|категорию|категории|раздел|расскажи про|расскажи о|что можно с|что можно в|"
                             r"команды для|команды про|команды) (.+)")


def categories_message(context: Sequence[str] = ()) -> Tuple[str, Tuple[str, ...]]:
    names = tuple(name for name, _stems, _commands in CATEGORIES)
    spoken = "; ".join("{}. {}".format(number, name) for number, name in enumerate(names, 1))
    head = ""
    if context:
        head = "Сейчас можно сказать: {}. ".format(", ".join("«{}»".format(item) for item in context))
    return (head + "Я умею вот что: " + spoken + ". Скажите: категория, и номер или название. "
            "Любую команду можно сказать и сразу."), names


def find_category(spoken: str) -> Optional[int]:
    """Index of the category named by «три», «третья», «флешки», «папки и файлы»; None when unclear."""
    number = parse_index(spoken)
    if number is not None:
        return number - 1 if 0 < number <= len(CATEGORIES) else None
    words = spoken.replace("ё", "е").split()
    found = [index for index, (_name, stems, _commands) in enumerate(CATEGORIES)
             if any(word.startswith(stem.replace("ё", "е")) for word in words for stem in stems)]
    return found[0] if len(set(found)) == 1 else None


def category_message(index: int) -> Tuple[str, Tuple[str, ...]]:
    name, _stems, commands = CATEGORIES[index]
    return "{}. Можно сказать: {}.".format(name[0].upper() + name[1:], "; ".join(commands)), commands
