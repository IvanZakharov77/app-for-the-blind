"""Optional Vosk microphone loop and local speech output."""

import difflib
import json
import re
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from .core import Assistant, Result, normalize
from .drives import VolumeWatcher, scan_volumes, volume_arrival_message
from . import __version__
from .updater import UPDATING


def extract_final_text(payload: str) -> str:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError):
        return ""
    if not isinstance(value, dict):
        return ""
    return value.get("text", "").strip() if isinstance(value.get("text"), str) else ""


# The assistant is called Vega. A conversation starts with «Привет, Вега»; she answers and listens.
NAME = "Вега"
GREETING = "Привет! Чем я могу помочь?"
GREETING_WORDS = ("привет", "здравствуй", "здравствуйте")
# Spellings the Russian Vosk model may give for «Вега» (its vocabulary decides; «века» is the usual slip).
NAME_VARIANTS = ("вега", "века", "вегу", "веге")
LISTEN_SECONDS = 10.0   # after the greeting: time to start saying the command
# After an answer, how long «дальше», «да», «второй» work without a new greeting. Ivan, 2026-10-15:
# none, every command starts with «Привет, Вега» (or «Вега»), otherwise she does not react.
FOLLOWUP_SECONDS = 0.0
# Ivan, 2026-10-15: after «Привет, Вега» people stop to think; a pause or «ну… это…» must not lose the command.
THINKING_SECONDS = 5.0
FILLERS = {"э", "эм", "ээ", "эээ", "м", "мм", "ммм", "а", "ну", "так", "это", "вот", "значит", "сейчас", "щас",
           "слушай", "подожди", "погоди", "как", "его", "там", "и"}
NAME_ONLY = ("вега", "века")  # «Вега, дальше» wakes her too
CHAT_START = ("хочу поговорить", "давай поговорим", "поговори со мной", "давай поболтаем", "хочу поболтать",
              "режим разговора", "включи режим разговора", "поговорим", "мне скучно давай поговорим")
CHAT_END = ("хватит", "вега хватит", "закончим разговор", "заканчиваем разговор", "конец разговора", "стоп разговор",
            "выключи режим разговора", "хватит разговаривать", "пока", "до свидания", "все спасибо", "спасибо хватит")
UPDATE_PHRASES = ("проверь обновления", "проверь обновление", "обнови вегу", "обновись", "обнови себя", "обнови программу",
                  "есть ли обновления", "есть обновления", "есть новая версия", "обновление", "обновления", "обновить вегу")
VERSION_PHRASES = ("какая у тебя версия", "какая версия", "какая версия веги", "какая у тебя программа версия", "твоя версия")
CHAT_IDLE = 120.0  # seconds of silence that end a conversation
CHAT_HELLO = "Давайте поговорим. Говорите, я слушаю. Чтобы закончить, скажите: Вега, хватит."
CHAT_BYE = "Хорошо, заканчиваем разговор. Если понадоблюсь, скажите: Привет, Вега."
CHAT_FAILED = "Не получилось связаться с Gemini. Проверьте интернет и скажите ещё раз."
CHAT_UNAVAILABLE = "Разговор работает в версии Веги с Gemini. Её можно выбрать при установке."
GOODBYE = ("спасибо", "спасибо вега", "все", "пока", "хватит", "ничего", "отбой")


def parse_wake(phrase: str):
    """«привет вега» → (True, ""); «привет вега который час» → (True, "который час"); else (False, "")."""
    command = normalize(phrase)
    for greeting in GREETING_WORDS:
        for name in NAME_VARIANTS:
            prefix = greeting + " " + name
            if command == prefix:
                return True, ""
            if command.startswith(prefix + " "):
                return True, command[len(prefix) + 1:]
    for name in NAME_ONLY:
        if command == name:
            return True, ""
        if command.startswith(name + " "):
            return True, command[len(name) + 1:]
    return False, ""


def strip_wake_word(phrase: str) -> str:
    """The command said together with the greeting, or "" when there is none."""
    return parse_wake(phrase)[1]


def strip_name(command: str) -> str:
    """«вега дальше» inside a conversation is just «дальше»."""
    for name in NAME_VARIANTS:
        if command.startswith(name + " "):
            return command[len(name) + 1:]
    return command


# Never a bare «замолчи»: the microphone also hears Vega herself, and help pages say that word.
# «Стоп», «остановись», «хватит» Vega never says herself, so they stop a long list too (Ivan, 2026-10-14).
STOP_PHRASES = ("вега замолчи", "века замолчи", "стоп", "остановись", "хватит", "вега стоп", "вега остановись", "вега хватит",
                "века стоп", "века остановись", "достаточно", "хватит читать", "стоп стоп", "хватит хватит", "прекрати",
                "перестань", "стой", "вега стой", "вега достаточно")


class StopWordDetector:
    def __init__(self, recognizer):
        self.recognizer = recognizer

    def reset(self) -> None:
        self.recognizer.Reset()

    def __call__(self, audio: bytes) -> bool:
        if self.recognizer.AcceptWaveform(audio):
            phrase = extract_final_text(self.recognizer.Result())
        else:
            try:
                value = json.loads(self.recognizer.PartialResult())
            except (TypeError, ValueError):
                return False
            phrase = value.get("partial", "") if isinstance(value, dict) else ""
        return isinstance(phrase, str) and is_stop_phrase(phrase)


def is_stop_phrase(phrase: str) -> bool:
    """«стоп», «Вега, замолчи», «Привет, Вега, остановись». A bare «замолчи» never: help texts say it."""
    words = normalize(phrase).split()
    if " ".join(words) in STOP_PHRASES:
        return True
    return len(words) >= 2 and words[-1] in ("стоп", "остановись", "хватит", "замолчи", "замолчите", "помолчи") \
        and any(word in NAME_VARIANTS for word in words[:-1])


class CommandBiasedRecognizer:
    """Two Vosk recognizers on the same audio: the free one hears anything, the command-only one
    (a grammar of Vega's own phrases) can only choose among commands. Unclear speech, an old person's
    or a quiet one, is often heard by the free model as near-nonsense while the command grammar still
    picks the right phrase. The command result is used only when the free text is not a command
    itself and has about as many words; free words («найди на ютубе …», notes) are never replaced."""

    def __init__(self, free, commands):
        self.free = free
        self.commands = commands
        self.heard_commands = []
        self.free_only = False  # in a free conversation the words are the person's own, never a command

    def AcceptWaveform(self, audio) -> bool:
        if self.commands.AcceptWaveform(audio):
            self.heard_commands.append(extract_final_text(self.commands.Result()))
        return self.free.AcceptWaveform(audio)

    def PartialResult(self):
        return self.free.PartialResult()

    def Result(self):
        free_text = extract_final_text(self.free.Result())
        self.heard_commands.append(extract_final_text(self.commands.FinalResult()))
        grammar_text = " ".join(text for text in self.heard_commands if text).strip()
        self.heard_commands = []
        self.commands.Reset()
        text = free_text if self.free_only else choose_heard(free_text, grammar_text)
        return json.dumps({"text": text}, ensure_ascii=False)

    def Reset(self):
        self.free.Reset()
        self.commands.Reset()
        self.heard_commands = []


def choose_heard(free_text: str, grammar_text: str) -> str:
    from .understanding import canonical, is_known_command
    free = normalize(free_text)
    woke, command = parse_wake(free)
    command = command if woke else strip_name(free)
    if not free or not grammar_text or "unk" in grammar_text:
        return free_text
    if not command or is_known_command(canonical(command)):
        return free_text
    grammar = normalize(grammar_text)
    g_woke, g_command = parse_wake(grammar)
    g_command = g_command if g_woke else strip_name(grammar)
    if not g_command or abs(len(g_command.split()) - len(command.split())) > 1:
        return free_text
    return ("привет вега " + g_command) if woke and not g_woke else grammar


def speak_with_mic_paused(stream, speaker, message: str) -> None:
    stream.stop()
    try:
        speaker.say(message)
        speaker.runAndWait()
    finally:
        stream.start()


TAIL_BLOCKS = 4  # the last second of microphone audio while Vega speaks (blocks of 0.25 s)


LONG_TEXT = 200   # longer answers (a folder, a page, a list) are read in parts
GAP_BLOCKS = 2    # 0.5 s of listening between the parts


def speech_parts(message: str, limit: int = LONG_TEXT) -> list:
    """A long answer split at sentence ends into parts of about limit characters; a short one whole."""
    if len(message) <= limit:
        return [message]
    sentences = re.split(r"(?<=[.!?;])\s+", message.strip())
    parts = []
    for sentence in sentences:
        if parts and len(parts[-1]) + 1 + len(sentence) <= limit:
            parts[-1] += " " + sentence
        else:
            parts.append(sentence)
    return [part for part in parts if part]


def speak_interruptibly(stream, speaker, message: str, stop_detector, tail: Optional[list] = None) -> bool:
    """Pump speech and the microphone on one thread; return whether speech was stopped.

    A long answer is read in parts with half a second of silence between them (Ivan, 2026-10-27:
    during a long folder or page «хватит» was not heard). While Vega speaks, her own loud voice
    drowns the person's in the microphone; in the pauses the microphone hears only the person.

    tail, when given, receives the last second of microphone audio heard while she spoke: a person
    often starts the next command before Vega has finished, and without it the recognizer gets the
    phrase without its first word («музыку» for «найди музыку», Ivan, 2026-10-15)."""
    recent = []
    if hasattr(stop_detector, "reset"):
        stop_detector.reset()
    parts = speech_parts(message)
    for index, part in enumerate(parts):
        finished = False

        def on_finished(_name, _completed):
            nonlocal finished
            finished = True

        token = speaker.connect("finished-utterance", on_finished)
        loop_started = False
        try:
            speaker.say(part)
            speaker.startLoop(False)
            loop_started = True
            while not finished:
                speaker.iterate()
                if finished:
                    break
                audio, _overflow = stream.read(4000)
                if stop_detector(bytes(audio)):
                    speaker.stop()
                    return True
                recent = (recent + [bytes(audio)])[-TAIL_BLOCKS:]
        finally:
            if loop_started:
                speaker.endLoop()
            speaker.disconnect(token)
        if index < len(parts) - 1:
            for _ in range(GAP_BLOCKS):
                audio, _overflow = stream.read(4000)
                if stop_detector(bytes(audio)):
                    return True
                recent = (recent + [bytes(audio)])[-TAIL_BLOCKS:]
    if tail is not None:
        tail.extend(recent)
    return False


def format_outcome(phrase: str, result: Result) -> str:
    """What is spoken: the answer itself, like a person would say it.

    Status stays honest through the wording: a failure starts with «Не получилось», an action
    that could not be checked says so, and «готово» is never claimed for those.
    """
    message = result.message.strip()
    if result.status == "error":
        return "Не получилось. " + message
    if result.status == "unverified":
        return message if message else "Команда передана, результат не проверен."
    if result.status == "unknown":
        return message or "Не понял. Скажите: помоги."
    return message or "Готово."


SLOW_SECONDS = 1.5
GEMINI_WAIT = "Запрос обрабатывается, подождите."


def execute_spoken_command(stream, speaker, assistant: Assistant, phrase: str, stop_detector,
                           acknowledge: Callable[[], None] = lambda: None, quiet_unknown: bool = False,
                           tail: Optional[list] = None, spoken: Optional[list] = None,
                           rescue: Optional[Callable[[str], Optional[str]]] = None, memory=None,
                           follow: Optional[Callable[[list], Optional[str]]] = None) -> Result:
    """Run the command; speak «Секунду» only when it takes noticeably long, then the answer."""
    if normalize(phrase) == "замолчи":
        speaker.stop()
        return assistant.handle(phrase)
    acknowledge()
    stream.stop()
    outcome = []
    asking = threading.Event()

    def work():
        try:
            learned = memory.recall(phrase) if memory is not None and normalize(phrase) else None
            if learned:
                # Said this way before and Gemini explained it: done at once, without the internet.
                result = assistant.handle(learned)
                if result.status not in RESCUED:
                    outcome.append(result)
                    return
                memory.forget(phrase)  # it no longer works: ask again below
            result = assistant.handle(phrase)
            if result.status in RESCUED and rescue is not None and not any(word in result.message for word in NOT_HEARD):
                asking.set()
                # The «with Gemini» edition (Ivan, 2026-10-15): everything Vega misheard, did not understand
                # or could not do («нет такой папки», «не нашла сайт») is heard again by Gemini.
                meant = rescue(result.message)
                if meant and meant.startswith("!"):
                    result = Result(result.status, result.message + " " + meant[1:], result.options)
                elif meant and "\n" not in meant and not meant.startswith("say:") and normalize(meant) != normalize(phrase):
                    retried = assistant.handle(meant)
                    if retried.status not in RESCUED or (result.status == "unknown" and retried.status != "unknown"):
                        result = retried
                    if retried.status not in RESCUED and memory is not None:
                        memory.learn(phrase, meant)
                    elif retried.status in RESCUED and follow is not None:
                        # Gemini's command did not work either: it sees why and tries another way.
                        result = run_plan(assistant, "more:", result, follow, [(meant, retried.message)])
                elif meant:
                    result = run_plan(assistant, meant, result, follow)
            if result.status == "unknown" and not normalize(phrase):
                result = Result("unknown", "Не расслышала. Скажите ещё раз, пожалуйста.")
            outcome.append(result)
        except Exception:
            outcome.append(Result("error", "Внутренняя ошибка при выполнении. Подробности записаны в журнал."))
    try:
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        waited = 0.0
        while worker.is_alive() and not asking.is_set() and waited < SLOW_SECONDS:
            worker.join(0.1)
            waited += 0.1
        if worker.is_alive():
            # Gemini on a slow connection can take many seconds: say so at once, not «Секунду».
            speaker.say(GEMINI_WAIT if asking.is_set() else "Секунду.")
            speaker.runAndWait()
            worker.join()
    finally:
        stream.start()
    result = outcome[0] if outcome else Result("error", "Внутренняя ошибка при выполнении.")
    if quiet_unknown and result.status == "unknown":
        # Overheard after an answer (a TV, a conversation in the room): not a command, stay silent.
        return result
    answer = format_outcome(phrase, result)
    if spoken is not None:
        spoken.append(answer)
    speak_interruptibly(stream, speaker, answer, stop_detector, tail)
    return result


LOG_LIMIT = 16 * 1024


def report_voice_failure(message: str, log_path: Path, beep=None) -> None:
    """Append one bounded diagnostic and signal an inaccessible microphone/TTS state."""
    if beep is None and sys.platform == "win32":
        import winsound
        beep = lambda: winsound.MessageBeep(winsound.MB_ICONHAND)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        previous = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        entry = "{} {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), message[:2048])
        log_path.write_text((previous + entry)[-LOG_LIMIT:], encoding="utf-8")
    except (OSError, UnicodeError):
        pass
    if beep is not None:
        try:
            beep()
        except (OSError, RuntimeError):
            pass


def describe_error(error: BaseException) -> str:
    return "{}: {}".format(type(error).__name__, error)


def sapi_russian_voice_ids() -> tuple:
    """Token ids of SAPI voices whose Language attribute is Russian (LCID 0x419)."""
    if sys.platform != "win32":
        return ()
    try:
        import win32com.client
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        ids = []
        # Women's voices first (Ivan, 2026-10-27: Vega must sound female when Piper does not start).
        for query in ("Language=419;Gender=Female", "Language=419"):
            tokens = voice.GetVoices(query)
            ids += [tokens.Item(index).Id for index in range(tokens.Count) if tokens.Item(index).Id not in ids]
        return tuple(ids)
    except Exception:
        return ()


# Russian women's voices of Windows and RHVoice, chosen before men's when nothing says which one.
FEMALE_NAMES = ("irina", "elena", "anna", "tatiana", "tatyana", "svetlana", "victoria", "elizaveta", "natalia",
                "milena", "katerina", "alena", "arina", "ирина", "елена", "анна", "татьяна", "светлана", "виктория")


def choose_russian_voice(voices: Iterable, preferred_name: Optional[str] = None, russian_ids: Iterable[str] = ()):
    """Pick the configured voice, else a SAPI voice marked Russian, else one named Russian.

    RHVoice voices on Windows 7 are called "Aleksandr", "Elena" and so on, so the
    name alone is not enough; the SAPI Language attribute is checked first.
    """
    voices = list(voices)
    if preferred_name:
        wanted = preferred_name.casefold()
        match = next((voice for voice in voices if wanted in str(voice.name).casefold()), None)
        if match is None:
            raise RuntimeError("Не найден голос «{}», выбранный в настройке.".format(preferred_name))
        return match
    for wanted_id in russian_ids:  # in the given order: women's voices come first
        match = next((voice for voice in voices if str(voice.id).casefold() == str(wanted_id).casefold()), None)
        if match is not None:
            return match
    voices.sort(key=lambda voice: not any(name in str(voice.name).casefold() for name in FEMALE_NAMES))
    for voice in voices:
        languages = str(getattr(voice, "languages", "")).lower()
        name = str(voice.name).lower()
        if "ru" in languages or "russian" in name or "русск" in name:
            return voice
    raise RuntimeError("Не найден установленный русский голос синтеза речи.")


def read_voice_setting(path: Path) -> Optional[str]:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    return value or None


def keep_listening(open_stream: Callable, session: Callable, on_failure: Callable,
                   sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                   max_failures: Optional[int] = None) -> None:
    """Run session(stream, recovered) and reopen the microphone after any failure.

    A failure after at least a minute of normal work starts the back-off from the beginning.
    """
    failures = 0
    while True:
        started = clock()
        try:
            with open_stream() as stream:
                session(stream, failures > 0)
                return
        except KeyboardInterrupt:
            raise
        except Exception as error:
            if clock() - started >= 60:
                failures = 0
            failures += 1
            on_failure(error, failures)
            if max_failures is not None and failures >= max_failures:
                raise RuntimeError("Микрофон не удалось восстановить: {}".format(describe_error(error))) from error
            sleep(min(60, 2 ** min(failures, 6)))


class ScreenReader:
    """Silences NVDA before VoiceAssist speaks, so two voices never talk over each other.

    Uses NVDA's own controller DLL when it is placed next to the program; otherwise does nothing.
    """

    def __init__(self, folders: Iterable[Path] = ()):
        self.library = None
        if sys.platform != "win32":
            return
        import ctypes
        name = "nvdaControllerClient64.dll" if sys.maxsize > 2 ** 32 else "nvdaControllerClient32.dll"
        for folder in folders:
            candidate = Path(folder) / name
            if candidate.is_file():
                try:
                    self.library = ctypes.WinDLL(str(candidate))
                except OSError:
                    self.library = None
                break

    def silence(self) -> None:
        if self.library is None:
            return
        try:
            if self.library.nvdaController_testIfRunning() == 0:
                self.library.nvdaController_cancelSpeech()
        except OSError:
            pass


def heard_tone() -> None:
    """A short soft tick: «услышал команду», instead of a spoken «ожидайте» every time."""
    if sys.platform == "win32":
        try:
            import winsound
            winsound.Beep(1200, 40)
        except (ImportError, RuntimeError):
            pass


def alert_signal() -> None:
    """A short system sound before a timer or reminder, heard even if speech is quiet."""
    if sys.platform == "win32":
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except (ImportError, RuntimeError):
            pass


def sleep_tone() -> None:
    """A low short tone: Vega stopped listening, say «Привет, Вега» again."""
    if sys.platform == "win32":
        try:
            import winsound
            winsound.Beep(600, 60)
        except (ImportError, RuntimeError):
            pass


def strip_echo(heard: str, said: str) -> str:
    """The microphone also hears the end of Vega's own answer. Drop the start of what was heard
    when it is the end of what she said: «чем я могу помочь найди музыку» → «найди музыку»."""
    words, own = normalize(heard).split(), normalize(said).split()
    best = 0
    for size in range(1, min(len(words), len(own)) + 1):
        piece, ending = " ".join(words[:size]), " ".join(own[-size:])
        if difflib.SequenceMatcher(None, piece, ending).ratio() >= 0.75:
            best = size
    return " ".join(words[best:]) if best else heard


AGENT_ROUNDS = 5  # times Gemini may look at the result and go on; a runaway loop ends here


def run_plan(assistant: Assistant, plan: str, failed: Result,
             follow: Optional[Callable[[list], Optional[str]]] = None, steps: Optional[list] = None) -> Result:
    """Gemini's commands in a row («открой блокнот», «напиши привет»), and its own spoken answer.

    With follow, Gemini works as an agent: after its steps, or a step that did not work, it gets
    Vega's answers and the new screen and gives the next steps, up to AGENT_ROUNDS times."""
    steps = list(steps or [])
    said, answer, status = [], "", "ok"
    for round_number in range(AGENT_ROUNDS + 1):
        lines = plan.split("\n")
        answer = next((line[4:] for line in lines if line.startswith("say:")), answer)
        more = "more:" in lines
        stuck = False
        for step in [line for line in lines if line and not line.startswith("say:") and line != "more:"]:
            result = assistant.handle(step)
            steps.append((step, result.message))
            said.append(result.message)
            if result.status in RESCUED:
                status, stuck = result.status, True
                break
            status = result.status if result.status != "ok" else status
            time.sleep(0.4)  # let the window or page from the previous step open
        if follow is None or not (more or stuck) or round_number == AGENT_ROUNDS:
            break
        time.sleep(0.6)  # the screen Gemini looks at next must show what the steps did
        plan = follow(steps) or ""
        if not plan or plan.startswith("!"):
            break
        status = "ok" if not stuck else status
        if not stuck:
            said = said[-1:]  # a long task: only the latest answer and the end are worth hearing
    if answer:
        said.append(answer)
        if status in RESCUED:
            status = "ok"  # Gemini explained what went wrong
    if not said:
        return failed
    return Result(status if status in RESCUED else "ok", " ".join(said[-4:]))


RESCUED = ("unknown", "error", "unavailable")  # results Gemini gets a second listen at
# Failures that are not about hearing: Gemini would only make the person wait for the same answer.
NOT_HEARD = ("расширени", "Проверьте интернет", "Chrome не открыт", "Окно Chrome не открыто")
UTTERANCE_BLOCKS = 60  # 15 seconds of 0.25 s blocks


def gemini_audio(blocks) -> bytes:
    from .gemini import wav_bytes
    return wav_bytes(blocks)


def listen_forever(stream, speaker, assistant: Assistant, recognizer, stop_detector, watcher, recovered: bool,
                   should_stop: Callable[[], bool] = lambda: False, after_command: Callable[[], None] = lambda: None,
                   signal: Callable[[], None] = alert_signal, acknowledge: Callable[[], None] = lambda: None,
                   clock: Callable[[], float] = time.monotonic, asleep: Callable[[], None] = sleep_tone,
                   greet: bool = False, acknowledge_wake: Callable[[], None] = lambda: None,
                   followup_seconds: float = FOLLOWUP_SECONDS,
                   rescue: Optional[Callable[[bytes, str, str], Optional[str]]] = None, memory=None,
                   remember: Callable[[str, str], None] = lambda heard, answer: None,
                   follow: Optional[Callable[[str, list], Optional[str]]] = None,
                   chat=None, updater=None) -> None:
    """«Привет, Вега» → «Привет! Чем я могу помочь?» → the command → the answer.

    After the greeting Vega listens LISTEN_SECONDS for the command. After each answer she keeps
    listening followup_seconds for a follow-up («дальше», «да», «открой второй»); by default none,
    so every command starts with «Привет, Вега» or «Вега». In a follow-up window the first phrase
    that is not a command gets «Не поняла» with what she heard; a second one in a row (a TV, people
    talking) ends the conversation silently. Anything said outside a conversation is ignored.
    """
    pending = []  # microphone audio heard while Vega was finishing an answer, fed to the recognizer first
    last_said = [""]
    utterance = []  # the audio of the phrase being recognized, for Gemini when the phrase is not understood
    echo = False  # the phrase being recognized began in that audio, so it may start with Vega's own last words
    talked = False  # Vosk showed words while this phrase was being said

    def say(message: str) -> None:
        last_said[0] = message
        speak_interruptibly(stream, speaker, message, stop_detector, pending)

    if recovered:
        say("Микрофон снова работает. Вега готова.")
    awake_until = None
    followup = False
    missed = 0  # follow-up phrases in a row that were not commands
    chatting = None  # «хочу поговорить»: the time of the last phrase while Vega talks with the person via Gemini
    last_spoken_to = clock()  # for self-update: it waits until nobody spoke to Vega for a while
    if greet:  # at start Vega speaks first and waits for the command, no «Привет, Вега» needed
        say(GREETING)
        awake_until = clock() + LISTEN_SECONDS
    while not should_stop():
        from_tail = bool(pending)
        if from_tail:
            audio = pending.pop(0)
        else:
            audio, _overflow = stream.read(4000)
        if watcher[0] is not None:
            try:
                arrivals = watcher[0].poll()
            except OSError:
                watcher[0] = None
                arrivals = ()
                speak_interruptibly(stream, speaker, "Наблюдение за дисками остановлено из-за ошибки.", stop_detector)
            for volume in arrivals:
                speak_interruptibly(stream, speaker, volume_arrival_message(volume), stop_detector)
        for alert in assistant.poll_due():
            if alert.startswith(("Таймер", "Напоминание", "Пропущено")):
                signal()
            speak_interruptibly(stream, speaker, alert, stop_detector)
        if chatting is not None and clock() - chatting > CHAT_IDLE:
            chatting = None
            _free_words(recognizer, False)
            chat.end_chat()
            say(CHAT_BYE)
            asleep()
        if (updater is not None and awake_until is None and chatting is None and not pending
                and updater.ready(clock() - last_spoken_to)):
            say(UPDATING)
            updater.install()
        utterance.append(bytes(audio))
        del utterance[:-UTTERANCE_BLOCKS]
        if not recognizer.AcceptWaveform(bytes(audio)):
            partial = getattr(recognizer, "PartialResult", None)
            talking = partial is not None and bool(_partial_text(partial()))
            echo = echo or (from_tail and talking)
            talked = talked or talking
            if awake_until is not None:
                if talking:
                    awake_until = max(awake_until, clock() + 2.0)  # still talking: do not cut the command off
                elif clock() > awake_until:
                    awake_until = None
                    asleep()
            continue
        text = extract_final_text(recognizer.Result())
        heard_audio, utterance[:] = list(utterance), []
        mumbled, talked = talked and not text, False
        if echo or from_tail:
            text = strip_echo(text, last_said[0]) if text else text
            if not normalize(text):
                echo = False
                continue  # only Vega's own voice was heard
        echo = False
        if not text:
            if mumbled and awake_until is not None:
                # «Привет, Вега… ммм…»: the person is thinking. Keep listening, do not answer.
                awake_until = max(awake_until, clock() + THINKING_SECONDS)
            continue
        if chatting is not None:
            woke, phrase = parse_wake(text)
            phrase = phrase if woke else strip_name(normalize(text))
            if not phrase or all(word in FILLERS for word in phrase.split()):
                continue
            chatting = clock()
            if phrase in CHAT_END:
                chatting = None
                _free_words(recognizer, False)
                chat.end_chat()
                say(CHAT_BYE)
                asleep()
            else:
                acknowledge()
                answer = chat.chat(gemini_audio(heard_audio), phrase)
                say((answer[1:] if answer.startswith("!") else answer) if answer else CHAT_FAILED)
                chatting = clock()
            recognizer.Reset()
            utterance.clear()
            continue
        woke, command = parse_wake(text)
        if woke and command and all(word in FILLERS for word in command.split()):
            command = ""  # «Привет, Вега, ну… это…»: still thinking, the command comes next
        if woke and not command:
            awake_until, followup, missed = clock() + LISTEN_SECONDS, False, 0
            # An empty PartialResult does not mean silence: Vosk may already
            # hold the first word of the command. Never reset or start TTS
            # at this boundary; the input stream and recognizer stay active.
            acknowledge_wake()
            continue
        if not woke:
            if awake_until is None:
                continue
            command = strip_name(normalize(text))
            if command and all(word in FILLERS for word in command.split()):
                awake_until = max(awake_until, clock() + THINKING_SECONDS)
                continue  # «ну… это…» while thinking of the command
            followup_now = followup
        else:
            followup_now = False
        last_spoken_to = clock()
        if command in UPDATE_PHRASES or command in VERSION_PHRASES:
            if command in VERSION_PHRASES:
                say("Моя версия {}.".format(__version__))
            elif updater is None:
                say("Обновление работает только в установленной Веге.")
            else:
                acknowledge()
                say(updater.ask())
            awake_until = None
            asleep()
            recognizer.Reset()
            utterance.clear()
            continue
        if command in CHAT_START:
            if chat is None:
                say(CHAT_UNAVAILABLE)
            else:
                chatting, awake_until = clock(), None
                _free_words(recognizer, True)
                say(CHAT_HELLO)
            recognizer.Reset()
            utterance.clear()
            continue
        if command in GOODBYE:
            if command.startswith("спасибо"):
                say("Пожалуйста.")
            awake_until = None
            asleep()
            recognizer.Reset()
            utterance.clear()
            continue
        spoken = []
        result = execute_spoken_command(stream, speaker, assistant, command, stop_detector, acknowledge,
                                        quiet_unknown=followup_now and missed >= 1, tail=pending, spoken=spoken,
                                        rescue=None if rescue is None else (lambda failed: rescue(gemini_audio(heard_audio), command, failed)),
                                        memory=memory,
                                        follow=None if follow is None else (lambda steps: follow(command, steps)))
        last_said[0] = spoken[-1] if spoken else ""
        remember(command, last_said[0])
        if followup_now and result.status == "unknown":
            missed += 1
            if missed >= 2:
                awake_until, missed = None, 0
                asleep()
            else:
                awake_until = clock() + followup_seconds
        elif followup_seconds > 0:
            awake_until, followup, missed = clock() + followup_seconds, True, 0
        else:
            awake_until, followup, missed = None, False, 0  # the next command needs «Привет, Вега» again
        after_command()
        recognizer.Reset()
        utterance.clear()


def _free_words(recognizer, on: bool) -> None:
    if isinstance(recognizer, CommandBiasedRecognizer):
        recognizer.free_only = on


def _partial_text(payload: str) -> str:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError):
        return ""
    return value.get("partial", "").strip() if isinstance(value, dict) and isinstance(value.get("partial"), str) else ""


def say_fatal(speaker, reason: str) -> None:
    """Vega has no window: when she cannot go on after speaking, she says so instead of falling silent."""
    try:
        speaker.say(reason + " Вега выключается. Подробности в файле ошибок.")
        speaker.runAndWait()
    except Exception:
        pass


SPEAKER_ATTEMPTS = 24
SPEAKER_RETRY_SECONDS = 5.0


def start_speaker(preferred, fallback, log, attempts: int = SPEAKER_ATTEMPTS, wait=time.sleep):
    """Say the first phrase; if the chosen voice fails, try the Windows voice. Right after Windows starts the sound
    device may not be ready yet, so keep trying for about two minutes instead of quitting silently."""
    last = None
    for attempt in range(1, attempts + 1):
        for make in (preferred, fallback):
            try:
                speaker = make()
                speaker.say("Вега запускается, подождите.")
                speaker.runAndWait()
                return speaker
            except Exception as error:
                last = error
                log("Голос не заработал, попытка {}: {}".format(attempt, describe_error(error)))
        if attempt < attempts:
            wait(SPEAKER_RETRY_SECONDS)
    raise RuntimeError("Синтез речи недоступен: {}".format(describe_error(last)))


def run_voice(model_path: Path, input_device: Optional[int] = None, config_dir: Optional[Path] = None) -> None:
    """Run locally; imports stay lazy so core works without audio packages."""
    config_dir = config_dir or Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist"
    try:
        import sounddevice as sd
        import pyttsx3
        from vosk import Model, KaldiRecognizer, SetLogLevel
    except ImportError as error:
        raise RuntimeError("Нет компонента речи: установите зависимости voice и проверьте микрофон.") from error
    if not model_path.is_dir():
        raise RuntimeError("Не найдена локальная русская модель Vosk.")
    # Speech first: on an old HDD the model takes many seconds to load, and silence would look like a hang.
    from .settings import Settings
    settings = Settings(config_dir / "settings.json")

    def sapi_speaker():
        engine = pyttsx3.init()
        voice = choose_russian_voice(engine.getProperty("voices"),
                                     read_voice_setting(config_dir / "voice.txt"), sapi_russian_voice_ids())
        engine.setProperty("voice", voice.id)
        return engine
    from .piper_voice import make_speaker
    speaker = start_speaker(
        lambda: make_speaker(settings.get("voice_engine"), (Path(sys.executable).parent, config_dir), sapi_speaker,
                             log=lambda message: report_voice_failure(message, config_dir / "last-error.log", beep=lambda: None))[0],
        sapi_speaker, lambda message: report_voice_failure(message, config_dir / "last-error.log", beep=lambda: None))
    try:
        from .model_path import latin_model_path
        SetLogLevel(-1)
        model = Model(str(latin_model_path(model_path)))
    except Exception as error:
        say_fatal(speaker, "Не удалось загрузить распознавание речи.")
        raise RuntimeError("Не удалось загрузить модель Vosk: {}".format(describe_error(error))) from error
    try:
        from .browser_commands import start_web
        from .settings import apply_to_speaker
        if input_device is None:
            input_device = settings.get("input_device")
        assistant = Assistant(web=start_web(config_dir, search_engine=settings.get("search_engine")), settings=settings)
        base_rate = speaker.getProperty("rate") or 200
        reader = ScreenReader((Path(sys.executable).parent, config_dir)) if settings.get("pause_for_screen_reader") else ScreenReader()
        original_say = speaker.say

        def say(text, *args, **kwargs):
            reader.silence()
            return original_say(text, *args, **kwargs)
        speaker.say = say

        def apply_settings():
            try:
                apply_to_speaker(speaker, settings, base_rate)
            except Exception:
                pass
        apply_settings()
        if settings.problem:
            speaker.say(settings.problem)
            speaker.runAndWait()
        from . import net
        net.problem_log = lambda message: report_voice_failure(message, config_dir / "last-error.log", beep=lambda: None)
        from .gemini import start_gemini
        from .phrase_memory import PhraseMemory
        memory = PhraseMemory(config_dir / "learned.json")
        from .gemini import describe_screen
        gemini = start_gemini(config_dir, lambda message: report_voice_failure(message, config_dir / "last-error.log", beep=lambda: None),
                              screen=lambda: describe_screen(assistant.system))
        from .updater import start_updater
        updater = start_updater(config_dir, lambda message: report_voice_failure(message, config_dir / "last-error.log", beep=lambda: None))
        watcher = [VolumeWatcher(scan_volumes)]
        try:
            watcher[0].start()
        except OSError:
            watcher[0] = None
        first_start = [True]

        def open_stream():
            return sd.RawInputStream(samplerate=16000, blocksize=4000, device=input_device, dtype="int16", channels=1)

        def session(stream, recovered):
            recognizer = KaldiRecognizer(model, 16000)
            try:
                from .understanding import grammar_phrases
                from .browser import BUILTIN_SITES
                sites = [name for names, _url in BUILTIN_SITES for name in names]
                recognizer = CommandBiasedRecognizer(recognizer, KaldiRecognizer(
                    model, 16000, json.dumps(grammar_phrases(sites) + ["[unk]"], ensure_ascii=False)))
            except Exception as error:  # the free recognizer alone still works
                report_voice_failure("Распознаватель команд не включился: " + describe_error(error), config_dir / "last-error.log", beep=lambda: None)
            stop_detector = StopWordDetector(KaldiRecognizer(model, 16000, json.dumps(list(STOP_PHRASES) + ["[unk]"], ensure_ascii=False)))
            greet = first_start[0]
            if first_start[0]:
                first_start[0] = False
                if watcher[0] is None:
                    speak_interruptibly(stream, speaker, "Не удалось включить наблюдение за дисками.", stop_detector)
            listen_forever(stream, speaker, assistant, recognizer, stop_detector, watcher, recovered, after_command=apply_settings,
                           acknowledge=heard_tone, greet=greet, acknowledge_wake=heard_tone,
                           rescue=None if gemini is None else gemini.understand, memory=memory,
                           remember=(lambda heard, answer: None) if gemini is None else gemini.remember,
                           follow=None if gemini is None else gemini.next_steps, chat=gemini, updater=updater)

        def on_failure(error, attempt):
            report_voice_failure("Сбой голосового режима, попытка {}: {}".format(attempt, describe_error(error)),
                                 config_dir / "last-error.log")
            if attempt == 1 or attempt % 10 == 0:
                try:
                    speaker.say("Микрофон недоступен. Проверьте подключение, я попробую снова.")
                    speaker.runAndWait()
                except Exception:
                    pass

        keep_listening(open_stream, session, on_failure)
    except KeyboardInterrupt:
        raise
    except Exception:
        say_fatal(speaker, "Произошла внутренняя ошибка.")
        raise
