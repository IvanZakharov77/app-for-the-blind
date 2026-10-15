"""Spoken phrases for Chrome, pages, catalogues, YouTube and video → BrowserCommands calls."""

import re
from typing import Optional

from .numbers import parse_index, words_to_number

KIND_WORDS = {
    "заголовки": "headings", "ссылки": "links", "кнопки": "buttons", "поля": "fields",
    "результаты": "results", "фильмы": "films",
}
SINGULAR = {
    "ссылку": "links", "ссылка": "links", "кнопку": "buttons", "кнопка": "buttons", "поле": "fields",
    "заголовок": "headings", "фильм": "films", "результат": "results", "видео": "results", "ролик": "results",
}
SIMPLE = {
    "новая вкладка": ("tab", "new"), "открой новую вкладку": ("tab", "new"),
    "закрой вкладку": ("tab", "close"), "следующая вкладка": ("tab", "next"), "предыдущая вкладка": ("tab", "prev"),
    "какие вкладки открыты": ("tabs",), "список вкладок": ("tabs",), "какие вкладки": ("tabs",),
    "назад": ("navigate", "back"), "вернись назад": ("navigate", "back"), "вернись к списку": ("navigate", "back"),
    "вперед": ("navigate", "forward"), "обнови": ("navigate", "reload"), "обнови страницу": ("navigate", "reload"),
    "открой историю": ("open_special", "history"), "открой закладки": ("open_special", "bookmarks"),
    "открой загрузки браузера": ("open_special", "downloads"), "открой загрузки в хроме": ("open_special", "downloads"),
    "загрузки браузера": ("open_special", "downloads"),
    "добавь в закладки": ("bookmark",), "прочитай закладки": ("recent", "bookmarks"), "прочитай историю": ("recent", "history"),
    "закрой хром": ("close_browser",), "закрой браузер": ("close_browser",), "закрой chrome": ("close_browser",),
    "закрой гугл хром": ("close_browser",), "закрой гугл": ("close_browser",), "выключи браузер": ("close_browser",),
    "выключи хром": ("close_browser",), "закрой интернет": ("close_browser",), "закрой все вкладки": ("close_browser",),
    "закрой хроме": ("close_browser",), "закрыть браузер": ("close_browser",), "закрыть хром": ("close_browser",),
    "что на странице": ("page_summary",), "где я на странице": ("page_summary",), "прочитай заголовок": ("page_summary",),
    "прочитай текст": ("read_text", True), "прочитай основной текст": ("read_text", True), "читай страницу": ("read_text", True),
    "прочитай страницу": ("read_text", True), "продолжи чтение": ("read_text", False),
    "прокрути вниз": ("scroll", "down"), "прокрути вверх": ("scroll", "up"),
    "в начало страницы": ("scroll", "top"), "в конец страницы": ("scroll", "bottom"),
    "прочитай результаты": ("results", 0), "что нашлось": ("results", 0), "что нашел": ("results", 0), "что найдено": ("results", 0),
    "какие фильмы здесь есть": ("films", 0), "какие фильмы есть": ("films", 0), "прочитай фильмы": ("films", 0),
    "какие фильмы здесь": ("films", 0), "какие фильмы": ("films", 0), "какие фильмы на странице": ("films", 0),
    "что за фильмы": ("films", 0), "какие тут фильмы": ("films", 0), "что есть посмотреть": ("films", 0),
    "какие видео здесь есть": ("results", 0), "какие видео есть": ("results", 0),
    "расскажи описание": ("description",), "прочитай описание": ("description",), "о чем фильм": ("description",),
    "пауза": ("video", "pause"), "поставь на паузу": ("video", "pause"), "стоп": ("video", "pause"), "останови видео": ("video", "pause"),
    "продолжи": ("video", "play"), "играй": ("video", "play"), "включи видео": ("video", "play"), "воспроизведи": ("video", "play"),
    "плей": ("video", "play"), "продолжи видео": ("video", "play"), "включи": ("video", "play"),
    "видео громче": ("video", "volume", 20), "громче видео": ("video", "volume", 20),
    "видео тише": ("video", "volume", -20), "тише видео": ("video", "volume", -20),
    "без звука": ("video", "mute"), "выключи звук видео": ("video", "mute"), "включи звук видео": ("video", "unmute"),
    "в начало видео": ("video", "start"), "с начала": ("video", "start"), "сначала": ("video", "start"),
    "полный экран": ("video", "fullscreen"), "на весь экран": ("video", "fullscreen"),
    "выйди из полного экрана": ("video", "exit_fullscreen"), "обычный экран": ("video", "exit_fullscreen"),
    "следующая серия": ("video", "next_episode"), "следующее видео": ("video", "next_episode"),
    "предыдущая серия": ("video", "prev_episode"),
    "пропусти рекламу": ("video", "skip_ad"),
    "что с видео": ("video", "state"), "где я в видео": ("video", "state"), "сколько осталось видео": ("video", "state"),
}
UNITS = {"секунд": 1, "секунду": 1, "секунды": 1, "минуту": 60, "минуты": 60, "минут": 60}


def _seek(command: str) -> Optional[float]:
    match = re.fullmatch(r"(?:перемотай )?(вперед|назад) на (?:(.+?) )?(секунду|секунды|секунд|минуту|минуты|минут)", command)
    if not match:
        return None
    amount = 1.0 if match.group(2) is None else (words_to_number(match.group(2)) or 0)
    seconds = amount * UNITS[match.group(3)]
    return seconds if match.group(1) == "вперед" else -seconds


def route(command: str, web, last_kind: Optional[str]):
    """BrowserOutcome for a phrase that is clearly about Chrome, or None.

    Bare «открой …», «включи …» after a list are left to route_followup, which the assistant
    calls only after its own sites and programs, so «открой блокнот» never picks a search result.
    """
    simple = SIMPLE.get(command)
    if simple:
        method, *args = simple
        return getattr(web, method)(*args)
    seek = _seek(command)
    if seek is not None:
        return web.video("seek", seek)
    match = re.fullmatch(r"(?:перейди на|открой) вкладку (?:номер )?(.+)|вкладка (?:номер )?(.+)", command)
    if match:
        number = parse_index(match.group(1) or match.group(2))
        if number:
            return web.tab("activate", number)
    match = re.fullmatch(r"прочитай (заголовки|ссылки|кнопки|поля)(?: на странице)?", command)
    if match:
        return web.page_list(KIND_WORDS[match.group(1)], 0)
    match = re.fullmatch(r"(?:найди|ищи) на странице (.+)", command)
    if match:
        return web.find(match.group(1))
    match = re.fullmatch(r"(?:найди|поищи|ищи) (?:в интернете|в яндексе|в гугле) (.+)", command)
    if match:
        return web.web_search(match.group(1))
    if LOCAL_MEDIA.search(command):
        return None  # «найди музыку на компьютере», «включи мою музыку»: the files on this computer
    # Ivan, 2026-10-15: «найди …» reads what was found; «включи …» starts the best match at once.
    play = command.split(" ", 1)[0] in PLAY_VERBS
    if re.fullmatch(r"(?:найди|поищи|включи|поставь) (?:музыку|песни|песню|какую-нибудь музыку|какую нибудь музыку)", command):
        # Ivan, 2026-10-15: «найди музыку» means YouTube, not the laptop.
        return web.youtube_play("музыка") if play else web.youtube_search("музыка")
    match = re.fullmatch(r"(?:найди|поищи|ищи|включи|покажи|поставь|воспроизведи) (?:на|в) (?:ютубе|ютуб|youtube)(?: видео| музыку| песню| фильм| клип)? (.+)", command) \
        or re.fullmatch(r"(?:найди|поищи|ищи|включи|поставь|воспроизведи) (?:музыку|песню|песни|клип|трек|видео|ролик) (.+)", command) \
        or re.fullmatch(r"(?:найди|поищи|ищи|включи|покажи|поставь) (?:фильм |видео |музыку |песню |клип )?(.+) (?:на|в) (?:ютубе|ютуб|youtube)", command)
    if match:
        return web.youtube_play(match.group(1)) if play else web.youtube_search(match.group(1))
    match = re.fullmatch(r"(?:открой|включи|покажи|запусти|поставь) (?:фильм |сериал |мультфильм |мультик |кино )?(.+) (?:на|в) ({})".format(FILM_SITE_WORDS), command)
    if match:
        from .film_sites import SPOKEN_SITES
        return web.film_open_on(SPOKEN_SITES[match.group(2)], match.group(1))
    # «Открой сайт кинокрад найди фильм Человек-паук», «открой ютуб и найди Высоцкого»: two commands in one breath.
    # The first word is often lost («сайт кино краб найди фильм …», commands.log), so the verb is optional.
    match = re.fullmatch(r"(?:(?:открой|зайди на|зайди в|перейди на) )?(?:сайт )?({}) (?:и )?(?:там )?(?:найди|поищи|ищи)(?: там)? (.+)".format(
        _searchable_sites()), command)
    if match:
        from .browser import builtin_site
        from .film_sites import site_of
        site, text = match.groups()
        key = site_of(builtin_site(site))
        if key:
            return web.film_search_on(key, re.sub(r"^(?:фильм|сериал|мультфильм|кино) ", "", text))
        return web.youtube_search(re.sub(r"^(?:видео|ролик|клип) ", "", text))
    match = re.fullmatch(r"(?:найди|поищи|ищи) (?:фильм |сериал |мультфильм |кино )?(.+) (?:на|в) ({})".format(FILM_SITE_WORDS), command) \
        or re.fullmatch(r"(?:найди|поищи|ищи) (?:на|в) ({}) (?:фильм |сериал |мультфильм |кино )?(.+)".format(FILM_SITE_WORDS), command)
    if match:
        from .film_sites import SPOKEN_SITES
        first, second = match.groups()
        site, text = (second, first) if second in SPOKEN_SITES else (first, second)
        return web.film_search_on(SPOKEN_SITES[site], text)
    match = re.fullmatch(r"найди (?:фильм|сериал|мультфильм) (.+)|найди на сайте (.+)", command)
    if match:
        outcome = web.site_search(match.group(1) or match.group(2))
        if match.group(1) and outcome.status == "unavailable" and outcome.message.startswith("На этой странице нет поля"):
            # Not on a film site: search YouTube instead of giving up.
            return web.youtube_search(match.group(1))
        return outcome
    # «Открой второй фильм», «нажми кнопку три», «перейди в поле номер один», «открой третий результат».
    match = re.fullmatch(r"(?:открой|нажми|выбери|перейди в|перейди на|включи|воспроизведи) (.+?) (ссылку|кнопку|поле|фильм|результат|видео|ролик)", command) \
        or re.fullmatch(r"(?:открой|нажми|выбери|перейди в|перейди на|включи|воспроизведи) (ссылку|кнопку|поле|фильм|результат|видео|ролик) (.+)", command)
    if match:
        first, second = match.groups()
        word, rest = (second, first) if second in SINGULAR else (first, second)
        kind = SINGULAR[word]
        if kind == "results" and last_kind == "films":
            kind = "films"
        number = parse_index(rest)
        if number:
            return web.activate(kind, number)
        if kind in ("films", "results"):
            return web.open_by_name(kind, rest)
    if command in ("выбери качество", "какое качество", "смени качество"):
        from .browser import BrowserOutcome
        return BrowserOutcome("unavailable", "Выбор качества в этом плеере пока не поддерживается.")
    return None


FILM_SITE_WORDS = "кинокраде|кинокрад|кино краде|кино крад|хд резке|хдрезке|резке|хд резку|хдрезку|резку|резка|филмиксе|фильмиксе|филмикс|фильмикс"

PLAY_VERBS = ("включи", "поставь", "воспроизведи", "покажи", "запусти")


def _searchable_sites() -> str:
    """Every spoken name of the film sites and YouTube, longest first so «хд резка» wins over «резка»."""
    from .browser import BUILTIN_SITES
    names = [name for names, url in BUILTIN_SITES if any(host in url for host in ("kinokrad", "rezka", "filmix", "youtube"))
             for name in names]
    return "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
LOCAL_MEDIA = re.compile(r"\b(?:на|в|с|из) (?:компьютер[аеу]?|ноутбук[аеу]?|ноуте|флешк[аеи])\b|^(?:включи|поставь|найди) (?:мою|мои) ")


def route_followup(command: str, web, last_kind: Optional[str]):
    """«Воспроизведи второй», «включи номер три», «воспроизведи Группу крови» after a list was read."""
    match = re.fullmatch(r"(?:воспроизведи|включи|открой|выбери|поставь|запусти) (.+)", command)
    if not match:
        return None
    target = match.group(1)
    if last_kind in ("films", "results", "links", "buttons", "headings", "fields"):
        number = parse_index(target)
        if number:
            return web.activate(last_kind, number)
        if last_kind in ("films", "results"):
            return web.open_by_name(last_kind, target)
        return None
    if command.startswith("воспроизведи "):
        # Nothing was listed yet: «воспроизведи Кино Группа крови» starts it from YouTube.
        return web.youtube_play(target)
    return None


class NoBrowser:
    """Stands in for BrowserCommands where the extension link cannot exist, so Chrome phrases get an honest answer."""

    last_list = None

    def __getattr__(self, name):
        from .browser import BrowserOutcome
        return lambda *args, **kwargs: BrowserOutcome(
            "unavailable", "Управление страницами и видео работает только на Windows с Chrome и расширением VoiceAssist.")
