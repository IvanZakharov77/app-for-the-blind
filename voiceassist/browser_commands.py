"""Voice-level Chrome commands over the extension bridge, each with a checked outcome."""

from typing import Optional
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


def clock_text(seconds: Optional[int]) -> str:
    if seconds is None:
        return "неизвестно"
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return "{}:{:02d}:{:02d}".format(hours, minutes, secs) if hours else "{}:{:02d}".format(minutes, secs)


class BrowserCommands:
    def __init__(self, bridge, search_template: str = SEARCH_ENGINES["яндекс"]):
        self.bridge = bridge
        self.search_template = search_template
        self.last_list: Optional[str] = None
        self.offsets = {}
        self.text_offset = 0

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
        _result, error = self._call("nav.open", {"url": url})
        return error or BrowserOutcome("unverified", "Адрес передан Chrome, страница загружается.")

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
        outcome = self.open_url(self.search_template.format(quote_plus(query)))
        if outcome.status in ("ok", "unverified"):
            self.last_list = "results"
            self.offsets["results"] = 0
            return BrowserOutcome("unverified", "Ищу «{}». Когда страница загрузится, скажите: прочитай результаты.".format(query))
        return outcome

    # Page reading

    def page_summary(self) -> BrowserOutcome:
        result, error = self._call("page.summary")
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
        return self._list("films", "films.list", offset)

    def results(self, offset: int = 0) -> BrowserOutcome:
        return self._list("results", "results.list", offset)

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
        result, error = self._call("films.find" if kind == "films" else "results.find", {"text": text})
        if error:
            return error
        if result.get("error"):
            return BrowserOutcome("error", "«{}» в списке не найдено. Скажите: прочитай результаты, и выберите номер.".format(text))
        self.last_list = None
        return BrowserOutcome("unverified", "Открываю {} «{}». Скажите: что с видео, чтобы проверить воспроизведение.".format(
            "номер {}:".format(result.get("number")) if result.get("number") else "", result.get("name", "")))

    def youtube_search(self, query: str) -> BrowserOutcome:
        outcome = self.open_url("https://www.youtube.com/results?search_query={}".format(quote_plus(query)))
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

    def read_text(self, from_start: bool) -> BrowserOutcome:
        offset = 0 if from_start else self.text_offset
        result, error = self._call("page.text", {"offset": offset})
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


def start_web(config_dir, enabled: Optional[bool] = None, search_engine: str = "яндекс"):
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
    return BrowserCommands(server, SEARCH_ENGINES.get(search_engine, SEARCH_ENGINES["яндекс"]))
