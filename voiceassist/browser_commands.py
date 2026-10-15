"""Voice-level Chrome commands over the extension bridge, each with a checked outcome."""

from typing import Callable, Optional
from urllib.parse import quote_plus

from .browser import BrowserOutcome
from .browser_bridge import BridgeError
from .numbers import plural

KIND_NAMES = {
    "headings": ("Заголовки", "заголовок"), "links": ("Ссылки", "ссылку"),
    "buttons": ("Кнопки", "кнопку"), "fields": ("Поля ввода", "поле"),
    "films": ("Фильмы", "фильм"), "results": ("Результаты", "результат"),
}
SEARCH_ENGINES = {
    "яндекс": "https://yandex.ru/search/?text={}",
    "гугл": "https://www.google.com/search?q={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
}


def _find_videos(query: str) -> Optional[list]:
    from .youtube_search import search
    return search(query)


def _search_films(key: str, query: str) -> Optional[list]:
    from .film_sites import search
    return search(key, query)


def _films_on(url: str) -> Optional[list]:
    from .film_sites import films_on
    return films_on(url)


def _read_page(url: str):
    from .page_reader import read_page
    return read_page(url)


def clock_text(seconds: Optional[int]) -> str:
    if seconds is None:
        return "неизвестно"
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return "{}:{:02d}:{:02d}".format(hours, minutes, secs) if hours else "{}:{:02d}".format(minutes, secs)


class BrowserCommands:
    def __init__(self, bridge, search_template: str = SEARCH_ENGINES["гугл"]):
        self.bridge = bridge
        self.search_template = search_template
        self.last_list: Optional[str] = None
        self.offsets = {}
        self.text_offset = 0
        # Without the extension a search or a site still opens: Chrome gets the address directly.
        self.plain_opener: Optional[Callable[[str], BrowserOutcome]] = None
        self.opened_plain = False
        # Without the extension Vega reads YouTube results herself (youtube_search) and keeps them here.
        self.video_finder: Callable[[str], Optional[list]] = _find_videos
        self.found_videos: Optional[list] = None
        # Film sites without the extension (film_sites): the page Vega opened and the films she read there.
        self.page_url: Optional[str] = None
        self.found_films: Optional[list] = None
        self.film_search: Callable[[str, str], Optional[list]] = _search_films
        self.page_films: Callable[[str], Optional[list]] = _films_on
        # Any other page Vega opened, read over HTTP without the extension (page_reader).
        self.page_reader: Callable[[str], object] = _read_page
        self.plain_page = None

    def note_opened(self, url: str) -> None:
        """A site Vega opened in the browser herself: «какие фильмы здесь» reads this page."""
        self.page_url = url
        self.found_films = None

    def _call(self, op: str, args: Optional[dict] = None, timeout: float = 10.0):
        try:
            return self.bridge.request(op, args or {}, timeout=timeout), None
        except BridgeError as error:
            return None, self._error(error.code)

    @staticmethod
    def _error(code: str) -> BrowserOutcome:
        if code == "not_connected":
            return BrowserOutcome("unavailable", "Chrome с расширением Vega не отвечает. Откройте Chrome; если не поможет, попросите близкого человека проверить расширение.")
        if code == "timeout":
            return BrowserOutcome("error", "Chrome не ответил вовремя. Результат неизвестен.")
        if code in ("not_web_page", "no_tab") or "Cannot access" in code or "chrome://" in code:
            return BrowserOutcome("unavailable", "Это служебная страница Chrome или вкладки нет. Её нельзя прочитать.")
        return BrowserOutcome("error", "Chrome сообщил об ошибке: {}.".format(code))

    # Tabs, navigation, bookmarks

    def tabs(self) -> BrowserOutcome:
        result, error = self._call("tabs.list")
        if error:
            return error
        tabs = result.get("tabs", [])
        if not tabs:
            return BrowserOutcome("ok", "Вкладок нет.")
        active = next((tab["number"] for tab in tabs if tab.get("active")), None)
        names = ["{}. {}".format(tab["number"], tab.get("title") or "без названия") for tab in tabs[:5]]
        return BrowserOutcome("ok", "Открыто {} {}. Активна {}. {}.".format(
            len(tabs), plural(len(tabs), ("вкладка", "вкладки", "вкладок")), active, "; ".join(names)))

    def tab(self, kind: str, number: Optional[int] = None) -> BrowserOutcome:
        op = {"new": "tabs.new", "close": "tabs.close", "next": "tabs.next", "prev": "tabs.prev",
              "activate": "tabs.activate"}[kind]
        result, error = self._call(op, {"number": number} if number else {})
        if error:
            return error
        if result.get("error") == "no_tab":
            return BrowserOutcome("error", "Вкладки с таким номером нет.")
        if kind == "new":
            return BrowserOutcome("ok", "Открыта новая вкладка.")
        if kind == "close":
            return BrowserOutcome("ok", "Вкладка «{}» закрыта.".format(result.get("title", "")))
        return BrowserOutcome("ok", "Активна вкладка «{}».".format(result.get("title", "")))

    def navigate(self, kind: str) -> BrowserOutcome:
        _result, error = self._call({"back": "nav.back", "forward": "nav.forward", "reload": "nav.reload"}[kind])
        if error:
            if kind != "reload" and error.status == "error":
                return BrowserOutcome("unavailable", "Дальше по истории вкладки перейти нельзя.")
            return error
        return BrowserOutcome("unverified", {"back": "Переход назад передан Chrome.", "forward": "Переход вперёд передан Chrome.",
                                             "reload": "Страница перезагружается."}[kind])

    def open_url(self, url: str) -> BrowserOutcome:
        self.opened_plain = False
        _result, error = self._call("nav.open", {"url": url})
        if error is not None and error.status == "unavailable" and self.plain_opener is not None:
            outcome = self.plain_opener(url)
            if outcome.status in ("ok", "unverified"):
                self.opened_plain = True
                self.note_opened(url)
                return BrowserOutcome("unverified", "Открываю в браузере.")
            return outcome
        return error or BrowserOutcome("unverified", "Адрес передан Chrome, страница загружается.")

    def _plain_search(self, where: str, query: str) -> BrowserOutcome:
        self.last_list = None
        return BrowserOutcome("unverified", "Открыла поиск {}«{}». Прочитать результаты я смогу, когда в Chrome будет установлено расширение Vega.".format(where, query))

    def open_special(self, page: str) -> BrowserOutcome:
        _result, error = self._call("open.special", {"page": page})
        names = {"history": "История", "downloads": "Загрузки", "bookmarks": "Закладки"}
        return error or BrowserOutcome("ok", "Открыта страница «{}».".format(names[page]))

    def bookmark(self) -> BrowserOutcome:
        result, error = self._call("bookmark.add")
        if error:
            return error
        if result.get("error"):
            return BrowserOutcome("unavailable", "Эту страницу нельзя добавить в закладки.")
        if result.get("done") == "exists":
            return BrowserOutcome("ok", "Страница «{}» уже есть в закладках.".format(result.get("title", "")))
        return BrowserOutcome("ok", "Страница «{}» добавлена в закладки.".format(result.get("title", "")))

    def recent(self, which: str) -> BrowserOutcome:
        result, error = self._call("bookmark.list" if which == "bookmarks" else "history.recent")
        if error:
            return error
        items = [item.get("title") or item.get("url") for item in result.get("items", [])][:5]
        if not items:
            return BrowserOutcome("ok", "Список пуст.")
        return BrowserOutcome("ok", "{}: {}.".format("Последние закладки" if which == "bookmarks" else "Недавние страницы", "; ".join(items)))

    def close_browser(self) -> BrowserOutcome:
        _result, error = self._call("browser.close")
        return error or BrowserOutcome("ok", "Окна Chrome закрыты.")

    def web_search(self, query: str) -> BrowserOutcome:
        self.found_videos = None
        outcome = self.open_url(self.search_template.format(quote_plus(query)))
        if self.opened_plain:
            return self._plain_search("", query)
        if outcome.status in ("ok", "unverified"):
            self.last_list = "results"
            self.offsets["results"] = 0
            return BrowserOutcome("unverified", "Ищу «{}». Когда страница загрузится, скажите: прочитай результаты.".format(query))
        return outcome

    # Page reading

    def page_summary(self) -> BrowserOutcome:
        result, error = self._call("page.summary")
        if error and error.status == "unavailable" and self._without_extension():
            from .film_sites import site_of
            if site_of(self.page_url) is not None:
                return self.films(0)  # «что на странице» on a film site Vega opened: its films
            return self._plain_summary()
        if error:
            return error
        counts = result.get("counts", {})
        parts = ["Страница «{}».".format(result.get("title") or "без названия")]
        if result.get("heading"):
            parts.append("Главный заголовок: {}.".format(result["heading"]))
        parts.append("Заголовков {}, ссылок {}, кнопок {}, полей {}.".format(
            counts.get("headings", 0), counts.get("links", 0), counts.get("buttons", 0), counts.get("fields", 0)))
        if result.get("films"):
            parts.append("Похоже на каталог: {} карточек. Скажите: какие фильмы здесь есть.".format(result["films"]))
        if result.get("videos"):
            parts.append("Есть видео.")
        return BrowserOutcome("ok", " ".join(parts))

    def _list(self, kind: str, op: str, offset: int) -> BrowserOutcome:
        args = {"offset": offset}
        if op == "page.list":
            args["kind"] = kind
        result, error = self._call(op, args)
        if error:
            return error
        items = result.get("items", [])
        total = result.get("total", 0)
        title, accusative = KIND_NAMES[kind]
        self.last_list = kind
        self.offsets[kind] = offset
        if not total:
            return BrowserOutcome("ok", "{} не найдены на этой странице.".format(title))
        if not items:
            return BrowserOutcome("ok", "Больше нет. Всего {}.".format(total))
        spoken = []
        for item in items:
            text = "{}. {}".format(item["number"], item["name"])
            if item.get("detail"):
                text += ", " + item["detail"]
            if item.get("level"):
                text += ", уровень {}".format(item["level"])
            spoken.append(text)
        end = items[-1]["number"]
        hint = " Скажите: дальше." if end < total else ""
        return BrowserOutcome("ok", "{} {} из {}: {}.{} Чтобы выбрать, скажите: открой {} номер.".format(
            title, "с {} по {}".format(items[0]["number"], end) if len(items) > 1 else items[0]["number"],
            total, "; ".join(spoken), hint, accusative))

    def page_list(self, kind: str, offset: int = 0) -> BrowserOutcome:
        return self._list(kind, "page.list", offset)

    def films(self, offset: int = 0) -> BrowserOutcome:
        if offset and self.found_films is not None:
            return self._film_list(offset)
        outcome = self._list("films", "films.list", offset)
        if outcome.status != "unavailable" or not self._without_extension():
            self.found_films = None
            return outcome
        from .film_sites import site_of
        if site_of(self.page_url) is None:
            return BrowserOutcome("unavailable", "Без расширения я читаю фильмы только на сайтах, которые открыла сама: "
                                                 "кинокрад, резка, филмикс. Скажите, например: Вега, открой кинокрад.")
        films = self.page_films(self.page_url)
        if films is None:
            return BrowserOutcome("error", "Сайт не ответил. Проверьте интернет и попробуйте ещё раз.")
        self.found_films = films
        return self._film_list(0)

    def _without_extension(self) -> bool:
        _result, error = self._call("tabs.list", timeout=3)
        return error is not None and error.status == "unavailable"

    def _film_list(self, offset: int, head: str = "") -> BrowserOutcome:
        films = self.found_films or []
        self.last_list = "films"
        self.offsets["films"] = offset
        page = films[offset:offset + 5]
        if not page:
            return BrowserOutcome("ok", head + ("Больше нет." if films else "Фильмов не нашла."))
        spoken = ["{}. {}{}".format(offset + number, item["name"], ", " + item["detail"] if item.get("detail") else "")
                  for number, item in enumerate(page, 1)]
        more = " Ещё: скажите «Вега, дальше»." if offset + 5 < len(films) else ""
        return BrowserOutcome("ok", "{}{}.{} Чтобы открыть, скажите: Вега, открой номер один.".format(head, "; ".join(spoken), more))

    def _open_film(self, number: Optional[int] = None, name: str = "") -> BrowserOutcome:
        films = self.found_films or []
        if number is not None:
            if not 0 < number <= len(films):
                return BrowserOutcome("error", "Номера {} нет. В списке {}.".format(number, len(films)))
            item = films[number - 1]
        else:
            wanted = name.lower().replace("ё", "е")
            item = next((film for film in films if wanted in film["name"].lower().replace("ё", "е")), None)
            if item is None:
                return BrowserOutcome("error", "«{}» в списке нет. Скажите: Вега, какие фильмы здесь, и выберите номер.".format(name))
        if self.plain_opener is None:
            return BrowserOutcome("unavailable", "Браузер не найден.")
        outcome = self.plain_opener(item["url"])
        if outcome.status not in ("ok", "unverified"):
            return outcome
        self.note_opened(item["url"])
        return BrowserOutcome("unverified", "Открываю «{}». Запустить видео голосом я смогу, когда в Chrome будет "
                                            "расширение Vega; пока нажмите на странице кнопку воспроизведения.".format(item["name"]))

    def film_search_on(self, key: str, text: str) -> BrowserOutcome:
        """«Найди фильм Человек-паук на кинокраде»: search that site, show its results page, read the films."""
        from .film_sites import SITES
        from urllib.parse import quote
        site = SITES[key]
        films = self.film_search(key, text)
        if films is None:
            return BrowserOutcome("error", "{} не ответил. Проверьте интернет и попробуйте ещё раз.".format(site.title))
        if self.plain_opener is not None:
            page = site.search_page.format(quote(text))
            if self.plain_opener(page).status in ("ok", "unverified"):
                self.page_url = page
        self.found_films = films
        if not films:
            self.last_list = None
            return BrowserOutcome("unavailable", "На сайте {} по запросу «{}» ничего не нашлось.".format(site.title, text))
        return self._film_list(0, "{}, «{}»: ".format(site.title, text))

    def results(self, offset: int = 0) -> BrowserOutcome:
        if self.found_videos is not None:
            return self._found_list(offset)
        return self._list("results", "results.list", offset)

    def _found_list(self, offset: int) -> BrowserOutcome:
        videos = self.found_videos or []
        self.last_list = "results"
        self.offsets["results"] = offset
        page = videos[offset:offset + 5]
        if not page:
            return BrowserOutcome("ok", "Больше нет." if videos else "Ничего не нашлось.")
        spoken = ["{}. {}{}".format(offset + number, item["name"], ", " + item["detail"] if item.get("detail") else "")
                  for number, item in enumerate(page, 1)]
        hint = " Ещё: скажите «дальше»." if offset + 5 < len(videos) else ""
        return BrowserOutcome("ok", "{}.{} Чтобы включить, скажите: включи номер один.".format("; ".join(spoken), hint))

    def _play_found(self, number: Optional[int] = None, name: str = "") -> BrowserOutcome:
        videos = self.found_videos or []
        if number is not None:
            if not 0 < number <= len(videos):
                return BrowserOutcome("error", "Номера {} нет. Найдено {}.".format(number, len(videos)))
            item = videos[number - 1]
        else:
            wanted = name.lower().replace("ё", "е")
            item = next((video for video in videos if wanted in video["name"].lower().replace("ё", "е")), None)
            if item is None:
                return BrowserOutcome("error", "«{}» среди найденного нет. Скажите: что нашлось, и выберите номер.".format(name))
        if self.plain_opener is None:
            return BrowserOutcome("unavailable", "Браузер не найден.")
        outcome = self.plain_opener(item["url"])
        if outcome.status not in ("ok", "unverified"):
            return outcome
        return BrowserOutcome("unverified", "Включаю «{}».".format(item["name"]))

    def more(self) -> Optional[BrowserOutcome]:
        """«Дальше» for the last page list; None when no list was read."""
        if self.last_list is None:
            return None
        if self.last_list == "text":
            return self.read_text(False)
        kind = self.last_list
        offset = self.offsets.get(kind, 0) + 5
        if kind == "films":
            return self.films(offset)
        if kind == "results":
            return self.results(offset)
        return self.page_list(kind, offset)

    def activate(self, kind: str, number: int) -> BrowserOutcome:
        if kind == "results" and self.found_videos is not None:
            return self._play_found(number)
        if kind == "films" and self.found_films is not None:
            return self._open_film(number)
        op, args = {"films": ("films.open", {}), "results": ("results.open", {})}.get(kind, ("page.activate", {"kind": kind}))
        args["number"] = number
        result, error = self._call(op, args)
        if error:
            return error
        problem = result.get("error")
        if problem == "no_list":
            return BrowserOutcome("error", "Сначала прочитайте список: например, скажите: прочитай {}.".format(KIND_NAMES[kind][0].lower()))
        if problem == "no_item":
            return BrowserOutcome("error", "Номера {} нет. В списке {}.".format(number, result.get("total", 0)))
        if problem == "changed":
            return BrowserOutcome("error", "Страница изменилась, список сброшен. Прочитайте его заново.")
        if result.get("done") == "focused":
            return BrowserOutcome("ok", "Курсор в поле «{}». Можно печатать.".format(result.get("name", "")))
        self.last_list = None
        return BrowserOutcome("unverified", "Нажато: «{}». Если откроется новая страница, скажите: что на странице.".format(result.get("name", "")))

    def open_by_name(self, kind: str, text: str) -> BrowserOutcome:
        """«Воспроизведи Дюну», «открой фильм Солярис»: pick by name from the current list."""
        if kind == "results" and self.found_videos is not None:
            return self._play_found(name=text)
        if kind == "films" and self.found_films is not None:
            return self._open_film(name=text)
        result, error = self._call("films.find" if kind == "films" else "results.find", {"text": text})
        if error:
            return error
        if result.get("error"):
            return BrowserOutcome("error", "«{}» в списке не найдено. Скажите: прочитай результаты, и выберите номер.".format(text))
        self.last_list = None
        return BrowserOutcome("unverified", "Открываю {} «{}». Скажите: что с видео, чтобы проверить воспроизведение.".format(
            "номер {}:".format(result.get("number")) if result.get("number") else "", result.get("name", "")))

    def youtube_search(self, query: str) -> BrowserOutcome:
        self.found_videos = None
        outcome = self.open_url("https://www.youtube.com/results?search_query={}".format(quote_plus(query)))
        if self.opened_plain:
            videos = self.video_finder(query)
            if not videos:
                return self._plain_search("на YouTube ", query)
            self.found_videos = videos
            listed = self._found_list(0)
            return BrowserOutcome("ok", "На YouTube нашла: " + listed.message)
        if outcome.status in ("ok", "unverified"):
            self.last_list = "results"
            self.offsets["results"] = 0
            return BrowserOutcome("unverified", "Ищу на YouTube «{}». Когда страница загрузится, скажите: что нашлось.".format(query))
        return outcome

    def description(self) -> BrowserOutcome:
        result, error = self._call("films.description")
        if error:
            return error
        if not result.get("text"):
            return BrowserOutcome("unavailable", "Описание на этой странице не найдено.")
        return BrowserOutcome("ok", "{}. {}".format(result.get("title", ""), result["text"]))

    def _plain_page(self):
        """The page Vega opened, downloaded and read without the extension; (page, outcome when it cannot be read)."""
        if not self.page_url:
            return None, BrowserOutcome("unavailable", "Любую страницу я читаю с расширением Vega в Chrome. Без него только те, "
                                                       "что открыла сама. Скажите, например: Вега, открой сайт википедия.")
        if self.plain_page is None or self.plain_page[0] != self.page_url:
            page = self.page_reader(self.page_url)
            if page is None:
                return None, BrowserOutcome("error", "Страница не ответила. Проверьте интернет и попробуйте ещё раз.")
            self.plain_page = (self.page_url, page)
        return self.plain_page[1], None

    def _plain_summary(self) -> BrowserOutcome:
        page, problem = self._plain_page()
        if problem:
            return problem
        parts = ["Страница «{}».".format(page.title or "без названия")]
        if page.headings:
            parts.append("Заголовки: {}.".format("; ".join(page.headings[:5])))
        parts.append("Чтобы послушать текст, скажите: Вега, прочитай страницу." if page.text else "Текста на ней я не нашла.")
        return BrowserOutcome("ok", " ".join(parts))

    def _plain_text(self, from_start: bool) -> BrowserOutcome:
        from .page_reader import chunk
        page, problem = self._plain_page()
        if problem:
            return problem
        offset = 0 if from_start else self.text_offset
        piece, self.text_offset = chunk(page.text, offset)
        if not piece:
            self.last_list = None
            return BrowserOutcome("ok", "Текст закончился." if offset else "Основной текст не найден.")
        more = self.text_offset < len(page.text)
        self.last_list = "text" if more else None
        return BrowserOutcome("ok", piece + (" Скажите: Вега, дальше." if more else " Конец текста."))

    def read_text(self, from_start: bool) -> BrowserOutcome:
        offset = 0 if from_start else self.text_offset
        result, error = self._call("page.text", {"offset": offset})
        if error and error.status == "unavailable" and self._without_extension():
            return self._plain_text(from_start)
        if error:
            return error
        if not result.get("text"):
            self.last_list = None
            return BrowserOutcome("ok", "Текст закончился." if offset else "Основной текст не найден.")
        self.text_offset = result.get("offset", 0)
        self.last_list = "text" if result.get("more") else None
        return BrowserOutcome("ok", result["text"] + (" Скажите: дальше." if result.get("more") else " Конец текста."))

    def find(self, text: str) -> BrowserOutcome:
        result, error = self._call("page.find", {"text": text})
        if error:
            return error
        count = result.get("count", 0)
        if not count:
            return BrowserOutcome("ok", "«{}» на странице не найдено.".format(text))
        return BrowserOutcome("ok", "Найдено {} {}. Первое: {}".format(count, plural(count, ("совпадение", "совпадения", "совпадений")), result.get("context", "")))

    def scroll(self, direction: str) -> BrowserOutcome:
        result, error = self._call("page.scroll", {"direction": direction})
        if error:
            return error
        return BrowserOutcome("ok", "Прокручено, позиция {} процентов страницы.".format(result.get("percent", 0)))

    def site_search(self, text: str) -> BrowserOutcome:
        result, error = self._call("page.search", {"text": text})
        if error and error.status == "unavailable" and self._without_extension():
            # No extension: search the film site that is open, Кинокрад when none is.
            from .film_sites import site_of
            return self.film_search_on(site_of(self.page_url) or "kinokrad", text)
        if error:
            return error
        if result.get("error"):
            return BrowserOutcome("unavailable", "На этой странице нет поля поиска, которое я умею заполнять.")
        self.last_list = "films"
        self.offsets["films"] = 0
        return BrowserOutcome("unverified", "Поиск «{}» отправлен сайту. Когда страница загрузится, скажите: какие фильмы здесь есть.".format(text))

    # Video

    def video(self, action: str, value: Optional[float] = None) -> BrowserOutcome:
        if action == "state":
            result, error = self._call("video.state")
            if error:
                return error
            if not result.get("found", True) or result.get("found") is False:
                return BrowserOutcome("unavailable", "На странице не найдено видео, которым я умею управлять.")
            return BrowserOutcome("ok", "Видео {}, позиция {} из {}, громкость {} процентов{}.".format(
                "на паузе" if result.get("paused") else "идёт", clock_text(result.get("time")),
                clock_text(result.get("duration")), result.get("volume"), ", звук выключен" if result.get("muted") else ""))
        args = {"action": action}
        if value is not None:
            args["value"] = value
        result, error = self._call("video.control", args, timeout=15)
        if error:
            return error
        problem = result.get("error")
        if result.get("found") is False:
            return BrowserOutcome("unavailable", "На странице не найдено видео, которым я умею управлять.")
        if result.get("done") == "skipped":
            return BrowserOutcome("ok", "Реклама пропущена.")
        if problem == "ad_not_skippable":
            return BrowserOutcome("unavailable", "Эту рекламу пока нельзя пропустить. Попробуйте через несколько секунд.")
        if problem == "no_ad":
            return BrowserOutcome("ok", "Рекламы сейчас нет.")
        if problem == "needs_gesture":
            return BrowserOutcome("unavailable", "Полный экран браузер включает только по нажатию клавиши. Нажмите клавишу F в плеере.")
        if problem == "no_episode":
            return BrowserOutcome("unavailable", "{} серии нет.".format("Следующей" if action == "next_episode" else "Предыдущей"))
        if problem:
            return BrowserOutcome("unavailable", "Этот плеер не поддерживает такую команду.")
        if result.get("done") == "episode":
            return BrowserOutcome("unverified", "Выбрана {}. Плеер загружает серию.".format(result.get("name", "серия")))
        before, after = result.get("before") or {}, result.get("after") or {}
        position = "Позиция {} из {}.".format(clock_text(after.get("time")), clock_text(after.get("duration")))
        if action == "play":
            if after.get("paused") is False:
                return BrowserOutcome("ok", "Видео воспроизводится. " + position)
            return BrowserOutcome("error", "Плеер не начал воспроизведение. Возможно, сайт ждёт нажатия на кнопку в самом плеере.")
        if action == "pause":
            return BrowserOutcome("ok", "Пауза. " + position) if after.get("paused") else BrowserOutcome("error", "Видео не остановилось.")
        if action in ("seek", "start"):
            expected = 0 if action == "start" else (before.get("time") or 0) + (value or 0)
            if after.get("time") is not None and abs(after["time"] - max(0, expected)) <= 5:
                return BrowserOutcome("ok", position)
            return BrowserOutcome("error", "Перемотка не сработала. " + position)
        if action == "volume":
            return BrowserOutcome("ok" if after.get("volume") != before.get("volume") or after.get("volume") in (0, 100) else "error",
                                  "Громкость видео {} процентов.".format(after.get("volume")))
        if action in ("mute", "unmute"):
            ok = after.get("muted") == (action == "mute")
            return BrowserOutcome("ok" if ok else "error", ("Звук видео выключен." if action == "mute" else "Звук видео включён.") if ok else "Плеер не изменил звук.")
        if action == "exit_fullscreen":
            return BrowserOutcome("ok", "Полноэкранный режим выключен." if not after.get("fullscreen") else "Видео осталось на весь экран.")
        return BrowserOutcome("unverified", "Команда передана плееру.")


def start_web(config_dir, enabled: Optional[bool] = None, search_engine: str = "гугл"):
    """Open the local link for the Chrome extension; NoBrowser when it cannot exist here.

    Only Windows has the extension's native host registered; VOICEASSIST_BRIDGE=1 enables it
    elsewhere for the end-to-end test.
    """
    import os
    import sys
    from .browser_bridge import BridgeServer
    from .browser_routes import NoBrowser
    if enabled is None:
        enabled = sys.platform == "win32" or os.environ.get("VOICEASSIST_BRIDGE") == "1"
    if not enabled:
        return NoBrowser()
    server = BridgeServer(config_dir / "bridge.json")
    try:
        server.start()
    except OSError:
        return NoBrowser()
    return BrowserCommands(server, SEARCH_ENGINES.get(search_engine, SEARCH_ENGINES["гугл"]))
