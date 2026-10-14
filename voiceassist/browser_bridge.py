"""Local link between VoiceAssist and the Chrome extension's native host.

VoiceAssist listens on 127.0.0.1 only. The native host, started by Chrome, reads the
port and a random token from the user's own %APPDATA%\\VoiceAssist\\bridge.json and must
send that token first. Messages are JSON lines; only operations in ALLOWED_OPS pass.
"""

import json
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from typing import Callable, Dict, Optional

ALLOWED_OPS = frozenset((
    "tabs.list", "tabs.new", "tabs.close", "tabs.next", "tabs.prev", "tabs.activate",
    "nav.back", "nav.forward", "nav.reload", "nav.open", "open.special",
    "bookmark.add", "bookmark.list", "history.recent", "browser.close",
    "page.summary", "page.list", "page.activate", "page.text", "page.find", "page.scroll", "page.search",
    "results.list", "results.open", "results.find", "films.find", "films.list", "films.open", "films.description",
    "video.state", "video.control",
))
MAX_LINE = 1024 * 1024


class BridgeError(Exception):
    """code: not_connected, timeout, refused or an error text from the extension."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def write_bridge_file(path: Path, port: int, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump({"port": port, "token": token, "pid": os.getpid()}, stream)
    temporary.replace(path)


def read_bridge_file(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("port"), int) or not isinstance(data.get("token"), str):
        return None
    return data


def _read_line(stream) -> Optional[dict]:
    line = stream.readline(MAX_LINE + 1)
    if not line:
        return None
    if len(line) > MAX_LINE:
        raise ValueError("too long")
    value = json.loads(line.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("not an object")
    return value


class BridgeServer:
    def __init__(self, bridge_file: Path, on_event: Optional[Callable[[dict], None]] = None):
        self.bridge_file = bridge_file
        self.on_event = on_event
        self.token = secrets.token_hex(16)
        self.listener: Optional[socket.socket] = None
        self.connection: Optional[socket.socket] = None
        self.writer = None
        self.lock = threading.Lock()
        self.pending: Dict[int, dict] = {}
        self.arrived = threading.Condition()
        self.next_id = 1
        self.connected_at = 0.0

    def start(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        self.listener = listener
        write_bridge_file(self.bridge_file, listener.getsockname()[1], self.token)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self) -> None:
        for item in (self.connection, self.listener):
            if item is not None:
                try:
                    item.close()
                except OSError:
                    pass

    @property
    def connected(self) -> bool:
        return self.connection is not None

    def _accept_loop(self) -> None:
        while True:
            try:
                connection, _address = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(connection,), daemon=True).start()

    def _serve(self, connection: socket.socket) -> None:
        reader = connection.makefile("rb")
        try:
            connection.settimeout(5)
            hello = _read_line(reader)
            if not hello or not secrets.compare_digest(str(hello.get("hello", "")), self.token):
                connection.close()
                return
            connection.settimeout(None)
            with self.lock:
                if self.connection is not None:
                    try:
                        self.connection.close()
                    except OSError:
                        pass
                self.connection = connection
                self.writer = connection.makefile("wb")
                self.connected_at = time.monotonic()
            while True:
                message = _read_line(reader)
                if message is None:
                    break
                if isinstance(message.get("id"), int):
                    with self.arrived:
                        self.pending[message["id"]] = message
                        self.arrived.notify_all()
                elif message.get("event") and self.on_event is not None:
                    try:
                        self.on_event(message)
                    except Exception:
                        pass
        except (OSError, ValueError, UnicodeError):
            pass
        finally:
            with self.lock:
                if self.connection is connection:
                    self.connection = None
                    self.writer = None
            try:
                connection.close()
            except OSError:
                pass

    def request(self, op: str, args: Optional[dict] = None, timeout: float = 10.0) -> dict:
        if op not in ALLOWED_OPS:
            raise BridgeError("refused")
        with self.lock:
            if self.writer is None:
                raise BridgeError("not_connected")
            identifier = self.next_id
            self.next_id += 1
            line = json.dumps({"id": identifier, "op": op, "args": args or {}}, ensure_ascii=False).encode("utf-8") + b"\n"
            try:
                self.writer.write(line)
                self.writer.flush()
            except OSError:
                raise BridgeError("not_connected")
        deadline = time.monotonic() + timeout
        with self.arrived:
            while identifier not in self.pending:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise BridgeError("timeout")
                self.arrived.wait(left)
            message = self.pending.pop(identifier)
        if not message.get("ok"):
            raise BridgeError(str(message.get("error") or "error"))
        result = message.get("result")
        return result if isinstance(result, dict) else {}
