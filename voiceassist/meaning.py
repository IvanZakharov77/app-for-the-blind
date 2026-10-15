"""Offline understanding of free wording (Ivan, 2026-10-15): no network, no neural net, instant on any PC.

A phrase no router took is rephrased the ways people actually speak, and each rephrasing is tried:
«можешь открыть блокнот пожалуйста» → «открой блокнот», «блокнот открой» → «открой блокнот»,
«хочу послушать высоцкого» → «включи песню высоцкого», «а теперь наоборот» after a copy or «громче»,
«сделай ещё раз» → the last command that worked.
"""

import re
from typing import List, Optional

# Infinitive and polite forms → the imperative the routers know.
VERBS = {
    "открыть": "открой", "закрыть": "закрой", "включить": "включи", "выключить": "выключи",
    "найти": "найди", "поискать": "найди", "поищи": "найди", "отыщи": "найди", "отыскать": "найди", "ищи": "найди",
    "показать": "покажи", "прочитать": "прочитай", "прочесть": "прочитай", "зачитай": "прочитай", "прочти": "прочитай",
    "почитай": "прочитай", "поставить": "поставь", "скопировать": "скопируй", "запустить": "запусти",
    "остановить": "останови", "сделать": "сделай", "перейти": "перейди", "вернуться": "вернись",
    "повторить": "повтори", "сказать": "скажи", "подскажи": "скажи", "подсказать": "скажи", "записать": "запиши", "написать": "напиши", "напомнить": "напомни",
    "извлечь": "извлеки", "переключиться": "переключись", "свернуть": "сверни", "развернуть": "разверни",
    "вруби": "включи", "врубить": "включи", "заведи": "включи", "сыграй": "включи", "проиграй": "включи",
    "вырубить": "выключи", "выруби": "выключи", "глянь": "покажи", "посмотри": "покажи",
    "отключи": "выключи", "отключить": "выключи", "убери": "закрой", "убрать": "закрой",
}
IMPERATIVES = frozenset(VERBS.values()) | {"скажи", "сколько", "какая", "какой", "какие", "что", "который", "где"}

# Words that only make the request polite or wrap it: dropped wherever they are.
SOFTENERS = ("пожалуйста", "будь добра", "будь добр", "будьте добры", "если можно", "если не трудно",
             "можешь", "можете", "могла бы", "мог бы", "можно", "давай", "давайте", "ка",
             "мне надо", "мне нужно", "надо", "нужно", "я прошу", "прошу", "попробуй", "помоги",
             "быстренько", "быстро", "срочно", "сейчас", "мне", "для меня", "тогда")

# «хочу послушать X» and the like: what people say when they want to watch or listen.
WANTS = (
    (r"^(?:я )?(?:хочу|хотел бы|хотела бы|хочется|можно) (?:послушать|слушать) (?:песню |музыку )?(.+)$", r"включи песню \1"),
    (r"^(?:я )?(?:хочу|хотел бы|хотела бы|хочется|можно) (?:посмотреть|смотреть) (?:на ютубе |ютуб )(.+)$", r"включи на ютубе \1"),
    (r"^(?:я )?(?:хочу|хотел бы|хотела бы|хочется|можно) (?:посмотреть|смотреть) фильм (.+)$", r"включи фильм \1 на кинокраде"),
    (r"^(?:я )?(?:хочу|хотел бы|хотела бы|хочется) (?:узнать|знать) (.+)$", r"\1"),
    (r"^(?:поставь|включи) (?:мне )?(?:песенку|песню) (.+)$", r"включи песню \1"),
    (r"^(?:а )?какая (?:сегодня |сейчас )?(?:на улице )?погода(?: на улице)?$", "какая погода"),
    (r"^сколько (?:сейчас )?времени$", "который час"),
    (r"^(?:какое|какой) (?:сегодня )?(?:число|день)$", "какое сегодня число"),
)

# «а теперь наоборот»: the same action the other way.
OPPOSITES = (("с первой на вторую", "со второй на первую"), ("с первой флешки на вторую", "со второй флешки на первую"),
             ("с первого диска на второй", "со второго диска на первый"), ("громче", "тише"), ("прибавь", "убавь"),
             ("включи звук", "выключи звук"), ("сверни", "разверни"), ("следующ", "предыдущ"), ("вперед", "назад"))
REVERSE = re.compile(r"^(?:а )?(?:теперь |сейчас |и )?(?:наоборот|в обратную сторону|обратно|назад наоборот)$")
AGAIN = re.compile(r"^(?:сделай |давай |выполни |повтори )?(?:ещ[её] раз(?: то же)?|то же самое|повтори команду|сделай так же|снова|опять)(?: сделай| давай| выполни)?$")


def _drop_softeners(text: str) -> str:
    for word in sorted(SOFTENERS, key=len, reverse=True):
        text = re.sub(r"(?:^| ){}(?= |$)".format(re.escape(word)), " ", text)
    return " ".join(text.replace(" ,", " ").split())


def _imperative(text: str) -> str:
    words = text.split()
    words = [VERBS.get(word, word) if index < 2 or word in VERBS and words[index - 1] in ("и", "а") else word
             for index, word in enumerate(words)]
    return " ".join(words)


def _verb_first(text: str) -> str:
    """«блокнот открой» → «открой блокнот»: the verb said last is moved to the front."""
    words = text.split()
    if len(words) >= 2 and words[-1] in IMPERATIVES and words[0] not in IMPERATIVES:
        return " ".join([words[-1]] + words[:-1])
    return text


def opposite(command: str) -> Optional[str]:
    for one, other in OPPOSITES:
        if one in command:
            return command.replace(one, other, 1)
        if other in command:
            return command.replace(other, one, 1)
    return None


def variants(command: str, previous: str = "") -> List[str]:
    """Other ways to read the command, most likely first; empty when there is nothing new to try."""
    found = []
    if previous and REVERSE.fullmatch(command):
        found.append(opposite(previous))
    if previous and AGAIN.fullmatch(command):
        found.append(previous)
    text = _imperative(_drop_softeners(command))
    for pattern, replacement in WANTS:
        if re.fullmatch(pattern, text):
            found.append(re.sub(pattern, replacement, text))
    found.append(text)
    found.append(_verb_first(text))
    if text.startswith("запусти "):
        found.append("открой " + text[len("запусти "):])
    if text.startswith(("скажи ", "расскажи ")):
        found.append(text.split(" ", 1)[1])  # «скажи который час» → «который час»
    if text.startswith("покажи "):
        found.append("открой " + text[len("покажи "):])
    result = []
    for item in found:
        if item and item != command and item not in result:
            result.append(item)
    return result
