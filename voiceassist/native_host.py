"""One-message Chrome Native Messaging host; no page content is executed."""

import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time

from .browser_bridge import ALLOWED_OPS, read_bridge_file
from .browser_state import save_active_tab


MAX_MESSAGE = 1024 * 1024


def _read_exact(stream, count: int) -> bytes:
    parts = []
    remaining = count
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise ValueError("Неполное сообщение браузера.")
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


def process_once(incoming, outgoing, state_path: Path, expected_origin: str, actual_origin: str, clock=time.time) -> None:
    if actual_origin.rstrip("/") != expected_origin.rstrip("/"):
        raise ValueError("Недопустимый отправитель расширения.")
    header = _read_exact(incoming, 4)
    length = struct.unpack("=I", header)[0]
    if not 1 <= length <= MAX_MESSAGE:
        raise ValueError("Недопустимый размер сообщения браузера.")
    payload = json.loads(_read_exact(incoming, length).decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("event") != "active_tab":
        raise ValueError("Недопустимое событие браузера.")
    url, title = payload.get("url"), payload.get("title")
    if not isinstance(url, str) or not isinstance(title, str):
        raise ValueError("Недопустимые поля вкладки.")
    save_active_tab(state_path, url, title, clock())
    body = json.dumps({"ok": True}).encode("utf-8")
    outgoing.write(struct.pack("=I", len(body)) + body)
    outgoing.flush()


def read_message(incoming) -> dict:
    header = _read_exact(incoming, 4)
    length = struct.unpack("=I", header)[0]
    if not 1 <= length <= MAX_MESSAGE:
        raise ValueError("Недопустимый размер сообщения браузера.")
    payload = json.loads(_read_exact(incoming, length).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Недопустимое сообщение браузера.")
    return payload


def write_message(outgoing, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_MESSAGE:
        raise ValueError("Слишком большое сообщение для браузера.")
    outgoing.write(struct.pack("=I", len(body)) + body)
    outgoing.flush()


class HostRelay:
    """Chrome stdin/stdout ⇄ VoiceAssist socket. Runs as long as Chrome keeps the port open."""

    def __init__(self, incoming, outgoing, config_dir: Path, clock=time.time, retry: float = 3.0):
        self.incoming = incoming
        self.outgoing = outgoing
        self.config_dir = config_dir
        self.clock = clock
        self.retry = retry
        self.socket = None
        self.socket_writer = None
        self.lock = threading.Lock()
        self.chrome_lock = threading.Lock()
        self.closed = threading.Event()

    def _connect(self) -> bool:
        info = read_bridge_file(self.config_dir / "bridge.json")
        if info is None:
            return False
        try:
            connection = socket.create_connection(("127.0.0.1", info["port"]), timeout=3)
            connection.settimeout(None)
            writer = connection.makefile("wb")
            writer.write(json.dumps({"hello": info["token"]}).encode("utf-8") + b"\n")
            writer.flush()
        except OSError:
            return False
        with self.lock:
            self.socket, self.socket_writer = connection, writer
        return True

    def _to_assistant(self, message: dict) -> None:
        with self.lock:
            writer = self.socket_writer
        if writer is None:
            return
        try:
            writer.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
            writer.flush()
        except OSError:
            self._drop()

    def _drop(self) -> None:
        with self.lock:
            connection, self.socket, self.socket_writer = self.socket, None, None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def _assistant_loop(self) -> None:
        while not self.closed.is_set():
            if self.socket is None and not self._connect():
                self.closed.wait(self.retry)
                continue
            reader = self.socket.makefile("rb")
            try:
                while True:
                    line = reader.readline(MAX_MESSAGE + 1)
                    if not line:
                        break
                    request = json.loads(line.decode("utf-8"))
                    # Only a known operation with plain arguments may reach the browser.
                    if (isinstance(request, dict) and isinstance(request.get("id"), int)
                            and request.get("op") in ALLOWED_OPS and isinstance(request.get("args", {}), dict)):
                        with self.chrome_lock:
                            write_message(self.outgoing, {"id": request["id"], "op": request["op"], "args": request.get("args", {})})
            except (OSError, ValueError, UnicodeError):
                pass
            self._drop()

    def run(self) -> None:
        threading.Thread(target=self._assistant_loop, daemon=True).start()
        try:
            while True:
                message = read_message(self.incoming)
                if message.get("event") == "active_tab":
                    url, title = message.get("url"), message.get("title")
                    if isinstance(url, str) and isinstance(title, str):
                        try:
                            save_active_tab(self.config_dir / "browser_state.json", url, title, self.clock())
                        except (OSError, ValueError):
                            pass
                        self._to_assistant({"event": "active_tab", "url": url, "title": title})
                elif isinstance(message.get("id"), int):
                    self._to_assistant({key: message.get(key) for key in ("id", "ok", "result", "error")})
        except (ValueError, OSError, UnicodeError):
            pass
        finally:
            self.closed.set()
            self._drop()


def main() -> int:
    if sys.platform != "win32":
        return 2
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    root = Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist"
    try:
        expected_id = (root / "extension-id.txt").read_text(encoding="ascii").strip()
        origin = "chrome-extension://{}/".format(expected_id)
        actual = next((arg for arg in sys.argv[1:] if arg.startswith("chrome-extension://")), "")
        if actual.rstrip("/") != origin.rstrip("/"):
            raise ValueError("Недопустимый отправитель расширения.")
    except (OSError, ValueError, UnicodeError) as error:
        print("VoiceAssist Native Messaging: {}".format(error), file=sys.stderr)
        return 3
    HostRelay(sys.stdin.buffer, sys.stdout.buffer, root).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
