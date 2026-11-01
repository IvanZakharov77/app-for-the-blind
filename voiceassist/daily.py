"""Reminders that repeat: «напоминай каждый день в девять утра выпить таблетки» (Ivan, 2026-11-01).

Days: every day, weekdays, weekends, or named days («по понедельникам и пятницам»). Several times
a day: «в девять и в двадцать один». When one comes, Vega asks to say «Вега, готово» and repeats it
twice more, ten minutes apart, until she hears it. One missed while the computer was off is named
after start, if it was within the last day.
"""

from datetime import datetime, timedelta
import re
from typing import List, Optional, Sequence, Tuple

from .numbers import replace_number_words

NAG_SECONDS = 600
NAG_TIMES = 2
EVERY_DAY = tuple(range(7))
DAY_STEMS = (("понедельник", 0), ("вторник", 1), ("сред", 2), ("четверг", 3), ("пятниц", 4), ("суббот", 5), ("воскресень", 6))
DAY_NAMES = ("понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям")
DONE_WORDS = ("готово", "сделала", "сделал", "сделано", "выпила", "выпил", "приняла", "принял", "выполнила",
              "выполнил", "выпила таблетки", "выпил таблетки", "приняла таблетки", "принял таблетки",
              "уже выпила", "уже выпил", "уже приняла", "уже принял", "я выпила", "я выпил", "я приняла", "я принял",
              "хорошо", "уже сделала", "уже сделал", "я сделала", "я сделал", "приняла лекарство",
              "принял лекарство", "выпила лекарство", "выпил лекарство", "уже приняла лекарство", "уже принял лекарство")

VERB = r"(?:напоминай|напоминать|напомни|напоминай мне|напомни мне|напоминать мне)"
PERIOD = (r"(?P<period>каждый день|ежедневно|каждое утро|каждый вечер|по будням|в будни|по рабочим дням|"
          r"по выходным|в выходные|(?:по|в|во) (?:понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)"
          r"(?:(?: и| ,)? (?:по |в |во )?(?:понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*))*)")
TIME = r"(\d{1,2})(?: (?:час|часа|часов))?(?: (?:0 )?(\d{1,2})(?: (?:минута|минуты|минут))?)?(?: (утра|дня|вечера|ночи))?"
TIMES = r"(?P<times>(?:в|во) {0}(?:(?: и| ,)? (?:в |во )?{0})*)".format(TIME)


def _days(period: str) -> Tuple[int, ...]:
    if period in ("каждый день", "ежедневно", "каждое утро", "каждый вечер"):
        return EVERY_DAY
    if period in ("по будням", "в будни", "по рабочим дням"):
        return (0, 1, 2, 3, 4)
    if period in ("по выходным", "в выходные"):
        return (5, 6)
    return tuple(sorted({number for stem, number in DAY_STEMS if stem in period}))


def _clock(hour: str, minute: Optional[str], part: Optional[str]) -> Optional[Tuple[int, int]]:
    hour_value, minute_value = int(hour), int(minute or 0)
    if part in ("дня", "вечера") and hour_value < 12:
        hour_value += 12
    if part == "ночи" and hour_value == 12:
        hour_value = 0
    if 0 <= hour_value <= 23 and 0 <= minute_value <= 59:
        return hour_value, minute_value
    return None


def parse(command: str) -> Optional[Tuple[Tuple[int, ...], List[Tuple[int, int]], str]]:
    """(days, times, what) for «напоминай каждый день в 9 и в 21 выпить таблетки»; None when not this.

    The text may also come first: «напоминай выпить таблетки каждый день в 9 утра»."""
    text = replace_number_words(command)
    if not re.match(VERB + r" ", text):
        return None
    text = re.sub("^" + VERB + " ", "", text)
    match = re.search(PERIOD + " " + TIMES, text) or re.search(TIMES + " " + PERIOD, text)
    period_only = None
    if match is None:
        period_only = re.search(PERIOD, text)
        if period_only is None:
            return None
        default = {"каждое утро": "в 9 утра", "каждый вечер": "в 9 вечера"}.get(period_only.group("period"))
        if default is None:
            return None
        text = text[:period_only.end()] + " " + default + text[period_only.end():]
        match = re.search(PERIOD + " " + TIMES, text)
    days = _days(match.group("period"))
    times = sorted({clock for clock in (_clock(*found) for found in re.findall(TIME, match.group("times"))) if clock})
    what = " ".join((text[:match.start()] + " " + text[match.end():]).split())
    if not days or not times or not what:
        return None
    return days, times, what


def next_due(days: Sequence[int], times: Sequence[Tuple[int, int]], after: datetime) -> datetime:
    """The first moment strictly after `after` on one of the days at one of the times."""
    for offset in range(8):
        day = (after + timedelta(days=offset)).date()
        if day.weekday() not in days:
            continue
        for hour, minute in sorted(times):
            moment = datetime(day.year, day.month, day.day, hour, minute)
            if moment > after:
                return moment
    raise ValueError("no days")


def describe(days: Sequence[int], times: Sequence[Tuple[int, int]]) -> str:
    """«каждый день в 09:00 и 21:00», «по будням в 08:30», «по понедельникам и пятницам в 10:00»."""
    days = tuple(sorted(days))
    if days == EVERY_DAY:
        when = "каждый день"
    elif days == (0, 1, 2, 3, 4):
        when = "по будням"
    elif days == (5, 6):
        when = "по выходным"
    else:
        names = [DAY_NAMES[day] for day in days]
        when = "по " + (", ".join(names[:-1]) + " и " + names[-1] if len(names) > 1 else names[0])
    clocks = ["{:02d}:{:02d}".format(*clock) for clock in sorted(times)]
    return "{} в {}".format(when, ", ".join(clocks[:-1]) + " и " + clocks[-1] if len(clocks) > 1 else clocks[0])


def parse_once(command: str, now: datetime) -> Optional[Tuple[datetime, str]]:
    """«напомни в три часа дня принять лекарство», «напомни завтра в 9 позвонить врачу» -> (when, what).

    Without «завтра» a time already past today means tomorrow."""
    text = replace_number_words(command)
    match = re.fullmatch(r"(?:напомни|напомнить|напоминай)(?: мне)?(?: (?P<day>сегодня|завтра|послезавтра))? (?:в|во) "
                         + "(?P<time>" + TIME + r") (?P<what>.+)", text)
    if match is None:
        match = re.fullmatch(r"(?:напомни|напомнить)(?: мне)? (?P<what>.+?)(?: (?P<day>сегодня|завтра|послезавтра))? (?:в|во) "
                             + "(?P<time>" + TIME + ")", text)
    if match is None:
        return None
    clock = _clock(*re.fullmatch(TIME, match.group("time")).groups())
    what = match.group("what").strip()
    if clock is None or not what or re.match(r"(?:через|каждый|по |ежедневно)", what):
        return None
    day = now.date() + timedelta(days={"завтра": 1, "послезавтра": 2}.get(match.group("day") or "", 0))
    when = datetime(day.year, day.month, day.day, *clock)
    if when <= now and not match.group("day"):
        when += timedelta(days=1)
    return when, what
