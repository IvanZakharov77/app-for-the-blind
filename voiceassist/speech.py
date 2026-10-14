"""Optional Vosk microphone loop and local speech output."""

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from .core import Assistant, Result, normalize
from .drives import VolumeWatcher, scan_volumes, volume_arrival_message


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
LISTEN_SECONDS = 8.0    # after the greeting: time to start saying the command
FOLLOWUP_SECONDS = 6.0  # after an answer: «дальше», «да», «второй» need no new greeting
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
STOP_PHRASES = ("вега замолчи", "века замолчи")


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
        return isinstance(phrase, str) and normalize(phrase) in STOP_PHRASES


def speak_with_mic_paused(stream, speaker, message: str) -> None:
    stream.stop()
    try:
        speaker.say(message)
        speaker.runAndWait()
    finally:
        stream.start()


def speak_interruptibly(stream, speaker, message: str, stop_detector) -> bool:
    """Pump speech and the microphone on one thread; return whether speech was stopped."""
    finished = False
    if hasattr(stop_detector, "reset"):
        stop_detector.reset()

    def on_finished(_name, _completed):
        nonlocal finished
        finished = True

    token = speaker.connect("finished-utterance", on_finished)
    loop_started = False
    try:
        speaker.say(message)
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
        return False
    finally:
        if loop_started:
            speaker.endLoop()
        speaker.disconnect(token)


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


def execute_spoken_command(stream, speaker, assistant: Assistant, phrase: str, stop_detector,
                           acknowledge: Callable[[], None] = lambda: None, quiet_unknown: bool = False) -> Result:
    """Run the command; speak «Секунду» only when it takes noticeably long, then the answer."""
    if normalize(phrase) == "замолчи":
        speaker.stop()
        return assistant.handle(phrase)
    acknowledge()
    stream.stop()
    outcome = []

    def work():
        try:
            outcome.append(assistant.handle(phrase))
        except Exception:
            outcome.append(Result("error", "Внутренняя ошибка при выполнении. Подробности записаны в журнал."))
    try:
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        worker.join(SLOW_SECONDS)
        if worker.is_alive():
            speaker.say("Секунду.")
            speaker.runAndWait()
            worker.join()
    finally:
        stream.start()
    result = outcome[0] if outcome else Result("error", "Внутренняя ошибка при выполнении.")
    if quiet_unknown and result.status == "unknown":
        # Overheard after an answer (a TV, a conversation in the room): not a command, stay silent.
        return result
    speak_interruptibly(stream, speaker, format_outcome(phrase, result), stop_detector)
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
        tokens = win32com.client.Dispatch("SAPI.SpVoice").GetVoices("Language=419")
        return tuple(tokens.Item(index).Id for index in range(tokens.Count))
    except Exception:
        return ()


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
    ids = {str(item).casefold() for item in russian_ids}
    for voice in voices:
        if str(voice.id).casefold() in ids:
            return voice
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


def listen_forever(stream, speaker, assistant: Assistant, recognizer, stop_detector, watcher, recovered: bool,
                   should_stop: Callable[[], bool] = lambda: False, after_command: Callable[[], None] = lambda: None,
                   signal: Callable[[], None] = alert_signal, acknowledge: Callable[[], None] = lambda: None,
                   clock: Callable[[], float] = time.monotonic, asleep: Callable[[], None] = sleep_tone) -> None:
    """«Привет, Вега» → «Привет! Чем я могу помочь?» → the command → the answer.

    After the greeting Vega listens LISTEN_SECONDS for the command. After each answer she keeps
    listening FOLLOWUP_SECONDS for a follow-up («дальше», «да», «открой второй»); a phrase that is
    not a command in that window is ignored silently. Anything said outside a conversation is ignored.
    """
    if recovered:
        speak_interruptibly(stream, speaker, "Микрофон снова работает. Вега готова.", stop_detector)
    awake_until = None
    followup = False
    while not should_stop():
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
        if not recognizer.AcceptWaveform(bytes(audio)):
            if awake_until is not None:
                partial = getattr(recognizer, "PartialResult", None)
                if partial is not None and _partial_text(partial()):
                    awake_until = max(awake_until, clock() + 2.0)  # still talking: do not cut the command off
                elif clock() > awake_until:
                    awake_until = None
                    asleep()
            continue
        text = extract_final_text(recognizer.Result())
        if not text:
            continue
        woke, command = parse_wake(text)
        if woke and not command:
            speak_interruptibly(stream, speaker, GREETING, stop_detector)
            awake_until, followup = clock() + LISTEN_SECONDS, False
            recognizer.Reset()
            continue
        if not woke:
            if awake_until is None:
                continue
            command = strip_name(normalize(text))
            followup_now = followup
        else:
            followup_now = False
        if command in GOODBYE:
            if command.startswith("спасибо"):
                speak_interruptibly(stream, speaker, "Пожалуйста.", stop_detector)
            awake_until = None
            asleep()
            recognizer.Reset()
            continue
        result = execute_spoken_command(stream, speaker, assistant, command, stop_detector, acknowledge, quiet_unknown=followup_now)
        if followup_now and result.status == "unknown":
            awake_until = None
            asleep()
        else:
            awake_until, followup = clock() + FOLLOWUP_SECONDS, True
        after_command()
        recognizer.Reset()


def _partial_text(payload: str) -> str:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError):
        return ""
    return value.get("partial", "").strip() if isinstance(value, dict) and isinstance(value.get("partial"), str) else ""


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
        SetLogLevel(-1)
        model = Model(str(model_path))
    except Exception as error:
        raise RuntimeError("Не удалось загрузить модель Vosk: {}".format(describe_error(error))) from error
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
        stop_detector = StopWordDetector(KaldiRecognizer(model, 16000, json.dumps(["вега замолчи", "века замолчи", "[unk]"], ensure_ascii=False)))
        if first_start[0]:
            first_start[0] = False
            speak_interruptibly(stream, speaker, "Вега готова. Скажите: привет, Вега.", stop_detector)
            if watcher[0] is None:
                speak_interruptibly(stream, speaker, "Не удалось включить наблюдение за дисками.", stop_detector)
        listen_forever(stream, speaker, assistant, recognizer, stop_detector, watcher, recovered, after_command=apply_settings, acknowledge=heard_tone)

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
