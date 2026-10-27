"""Natural neural voice through Piper (free, offline), behind the same interface as pyttsx3.

Piper runs as one long-lived process with the model loaded, so each phrase costs only
synthesis (well under real time on a 3rd-generation i5). Sound is played with winsound,
which every Windows has. If Piper is missing or fails, the caller falls back to SAPI.
"""

from array import array
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, List, Optional
import wave


def find_piper(folders) -> Optional[tuple]:
    """(piper.exe, model.onnx) from a «piper» folder next to the program or in the settings folder."""
    for folder in folders:
        root = Path(folder) / "piper"
        executable = root / ("piper.exe" if sys.platform == "win32" else "piper")
        if not executable.is_file():
            continue
        models = sorted(root.glob("*.onnx")) + sorted((root / "voices").glob("*.onnx"))
        models = [model for model in models if Path(str(model) + ".json").is_file()]
        if models:
            preferred = [model for model in models if "irina" in model.name or "denis" in model.name]
            return executable, (preferred or models)[0]
    return None


class PiperSpeaker:
    """Implements the pyttsx3 calls VoiceAssist uses: say, runAndWait, startLoop/iterate/endLoop,
    connect/disconnect('finished-utterance'), stop, getProperty/setProperty."""

    def __init__(self, executable: Path, model: Path, player=None, timeout: float = 60.0):
        # Piper cannot open paths with Cyrillic letters (a profile like «Пользователь»), like Vosk:
        # its folder and the sound folder get Latin-letter paths (Windows 8 laptop log, 2026-10-14).
        from .model_path import latin_model_path, latin_temp_folder
        executable, model = Path(executable), Path(model)
        if not str(executable).isascii() or not str(model).isascii():
            if model.parent == executable.parent:
                folder = latin_model_path(executable.parent, name="piper")
                executable, model = folder / executable.name, folder / model.name
        self.executable = executable
        self.model = model
        self.folder = latin_temp_folder()
        self.timeout = timeout
        self.properties = {"rate": 200, "volume": 1.0, "voice": self.model.stem, "voices": []}
        self.queue: List[str] = []
        self.callbacks = {}
        self.playing_until = 0.0
        self.current: Optional[Path] = None
        self.counter = 0
        self.lock = threading.Lock()
        self.player = player or WinsoundPlayer()
        self.process = None
        try:
            self._start()
        except BaseException:
            self._end()
            raise

    def _start(self) -> None:
        self.scale = self._wanted_scale()
        self._launch()
        self.synthesize("Проверка.")  # fails here, at start, rather than in the middle of a dialog

    def _wanted_scale(self) -> float:
        return round(200 / max(100, min(400, self.properties["rate"])), 2)

    def _launch(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [str(self.executable), "--model", str(self.model), "--json-input", "--quiet",
             "--output_dir", str(self.folder), "--length_scale", str(self.scale)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._errors(), creationflags=flags,
            cwd=str(self.executable.parent))

    def _errors(self):
        try:
            return open(str(self.folder / "piper-errors.txt"), "wb")
        except OSError:
            return subprocess.DEVNULL

    def _why(self) -> str:
        """Why Piper failed, for last-error.log: its exit code and the end of what it printed."""
        code = self.process.poll() if self.process is not None else None
        if code in (3221225781, -1073741515):  # 0xC0000135: a DLL is missing
            return " Не хватает библиотеки Windows (Visual C++)."
        try:
            text = (self.folder / "piper-errors.txt").read_bytes()[-300:].decode("utf-8", "replace").strip()
        except OSError:
            text = ""
        return "".join((" Код {}.".format(code) if code is not None else "", " " + text if text else ""))

    def synthesize(self, text: str) -> Path:
        with self.lock:
            if self._wanted_scale() != self.scale and self.process is not None:
                # Speed is a start option of Piper: restart once with the new one.
                self._end()
                self.scale = self._wanted_scale()
                self._launch()
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError("Голос Piper остановился." + self._why())
            self.counter += 1
            target = self.folder / "phrase{}.wav".format(self.counter % 4)
            if target.exists():
                target.unlink()
            line = json.dumps({"text": text, "output_file": str(target)}, ensure_ascii=False)
            self.process.stdin.write((line + "\n").encode("utf-8"))
            self.process.stdin.flush()
            answer = self._read_line()
            if not answer or not target.is_file():
                raise RuntimeError("Голос Piper не ответил." + self._why())
        volume = self.properties["volume"]
        if volume < 0.99:
            _scale(target, volume)
        return target

    def _read_line(self) -> bytes:
        result = []

        def read():
            result.append(self.process.stdout.readline())
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(self.timeout)
        if reader.is_alive():
            self.process.kill()
            return b""
        return result[0]

    # pyttsx3-compatible surface

    def getProperty(self, name):
        return self.properties.get(name)

    def setProperty(self, name, value) -> None:
        self.properties[name] = value

    def say(self, text: str, name=None) -> None:
        if text:
            self.queue.append(text)

    def runAndWait(self) -> None:
        while self.queue:
            path = self.synthesize(self.queue.pop(0))
            self.player.play(path, wait=True)

    def connect(self, event: str, callback: Callable) -> str:
        self.callbacks[event] = callback
        return event

    def disconnect(self, token: str) -> None:
        self.callbacks.pop(token, None)

    def startLoop(self, use_driver_loop: bool = True) -> None:
        self._next()

    def _next(self) -> bool:
        if not self.queue:
            self.current = None
            return False
        self.current = self.synthesize(self.queue.pop(0))
        self.playing_until = time.monotonic() + _duration(self.current)
        self.player.play(self.current, wait=False)
        return True

    def iterate(self) -> None:
        if self.current is not None and time.monotonic() >= self.playing_until:
            if not self._next():
                callback = self.callbacks.get("finished-utterance")
                if callback:
                    callback(None, True)
        elif self.current is None:
            callback = self.callbacks.get("finished-utterance")
            if callback:
                callback(None, True)
        time.sleep(0.01)

    def endLoop(self) -> None:
        self.current = None

    def stop(self) -> None:
        self.queue = []
        self.current = None
        self.player.stop()

    def _end(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        process.wait()
        for pipe in (process.stdin, process.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def close(self) -> None:
        self._end()


def _duration(path: Path) -> float:
    with wave.open(str(path), "rb") as stream:
        return stream.getnframes() / float(stream.getframerate())


def _scale(path: Path, volume: float) -> None:
    with wave.open(str(path), "rb") as stream:
        params = stream.getparams()
        frames = stream.readframes(stream.getnframes())
    with wave.open(str(path), "wb") as stream:
        stream.setparams(params)
        if params.sampwidth == 2:
            samples = array("h", frames)
            if sys.byteorder == "big":
                samples.byteswap()
            samples = array("h", (int(sample * volume) for sample in samples))
            if sys.byteorder == "big":
                samples.byteswap()
            frames = samples.tobytes()
        stream.writeframes(frames)


class WinsoundPlayer:
    """winsound first; when it cannot play («Failed to play sound», seen on Windows runners and
    suspected on Ivan's laptop, where Vega then fell back to the robotic Windows voice), the same
    sound goes out through sounddevice, which Vega already uses for the microphone."""

    def __init__(self):
        self.device = False  # True once winsound failed: sounddevice from then on
        self.stopped = False

    def play(self, path: Path, wait: bool) -> None:
        if not self.device:
            import winsound
            flags = winsound.SND_FILENAME | (0 if wait else winsound.SND_ASYNC)
            try:
                winsound.PlaySound(str(path), flags)
                return
            except RuntimeError:
                self.device = True
        with wave.open(str(path), "rb") as sound:
            data, rate, channels = sound.readframes(sound.getnframes()), sound.getframerate(), sound.getnchannels()
        self.stopped = False
        if wait:
            self._out(data, rate, channels)
        else:
            threading.Thread(target=self._out, args=(data, rate, channels), daemon=True).start()

    def _out(self, data: bytes, rate: int, channels: int) -> None:
        import sounddevice  # raw bytes: no numpy needed
        step = rate * channels * 2 // 10  # a tenth of a second, so stop() is quick
        with sounddevice.RawOutputStream(samplerate=rate, channels=channels, dtype="int16") as stream:
            for start in range(0, len(data), step):
                if self.stopped:
                    break
                stream.write(data[start:start + step])

    def stop(self) -> None:
        if self.device:
            self.stopped = True
            return
        import winsound
        winsound.PlaySound(None, 0)


# «auto» picks Piper only with this much RAM. Ivan, 2026-10-27: the Windows voice reads word by word
# and is unbearable; Piper's ~150 MB is fine on his 6 GB laptop, so only really small PCs skip it.
# 4 GB in 32-bit Windows shows as about 3.2 GB; Piper with Irina needs about 200 MB (Ivan, 2026-10-27).
PIPER_AUTO_MIN_RAM = 2.5 * 1024 ** 3


def total_memory() -> Optional[int]:
    if sys.platform != "win32":
        return None
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullTotalPhys)


def make_speaker(settings_engine: str, folders, sapi_factory: Callable, log: Callable[[str], None] = lambda message: None,
                 memory: Callable[[], Optional[int]] = total_memory):
    """Piper when chosen (or «auto», installed and enough RAM); otherwise SAPI through pyttsx3."""
    if settings_engine == "auto":
        ram = memory()
        if ram is not None and ram < PIPER_AUTO_MIN_RAM:
            try:
                speaker = sapi_factory()
            except Exception as error:
                # No Russian Windows voice (Windows 7 without RHVoice): Piper is better than silence.
                log("Русского голоса Windows нет ({}), включён Piper.".format(error))
            else:
                log("Памяти {:.1f} ГБ: включён лёгкий голос Windows. Piper можно выбрать в настройке.".format(ram / 1024 ** 3))
                return speaker, "sapi"
    if settings_engine in ("auto", "piper"):
        found = find_piper(folders)
        if found is not None:
            try:
                return PiperSpeaker(*found), "piper"
            except Exception as error:
                log("Голос Piper не запустился, включён голос Windows: {}".format(error))
        elif settings_engine == "piper":
            log("Голос Piper не найден в папке piper, включён голос Windows.")
    return sapi_factory(), "sapi"
