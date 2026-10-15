"""Loopback protocol for the dedicated Pro Meeting Chrome extension.

Chrome owns its normal user profile and tabs. The Python app owns audio bytes and
the single in-flight command. An uncertain send never retries automatically.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .config import CHUNKS_DIR

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8796
MAX_AUDIO_BYTES = 8 * 1024 * 1024
FILE_PART_BYTES = 192 * 1024
MAX_RESULT_BYTES = 200 * 1024
EXT_ID = re.compile(r"^[a-p]{32}$")


def chrome_executable() -> Path | None:
    """Find the installed Google Chrome executable."""
    candidates = [os.getenv("PRO_MEETING_CHROME_PATH")]
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if os.getenv(variable):
            candidates.append(str(Path(os.environ[variable]) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    for candidate in candidates:
        if candidate and Path(candidate.strip('"')).is_file():
            return Path(candidate.strip('"'))
    return None


def chrome_extension_profile() -> str:
    """Find the Chrome profile with this project's unpacked extension installed."""
    override = os.getenv("PRO_MEETING_CHROME_PROFILE", "").strip()
    if override:
        return override

    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("Không xác định được thư mục Chrome trong LOCALAPPDATA")
    user_data = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    extension_path = (Path(__file__).resolve().parent.parent / "extension").resolve()
    installed = []
    for profile in [user_data / "Default", *sorted(user_data.glob("Profile [0-9]*"))]:
        preferences = profile / "Secure Preferences"
        try:
            settings = json.loads(preferences.read_text(encoding="utf-8"))["extensions"]["settings"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if any(
            isinstance(entry, dict)
            and entry.get("path")
            and Path(entry["path"]).resolve() == extension_path
            for entry in settings.values()
        ):
            installed.append(profile.name)

    if not installed:
        raise RuntimeError(
            "Không tìm thấy Chrome profile có Pro Meeting ChatGPT Bridge. "
            "Hãy cài extension từ thư mục extension/ vào profile muốn sử dụng "
            "hoặc đặt PRO_MEETING_CHROME_PROFILE=\"Profile N\"."
        )
    if len(installed) > 1:
        try:
            state = json.loads((user_data / "Local State").read_text(encoding="utf-8"))
            last_used = state.get("profile", {}).get("last_used")
            if last_used in installed:
                return last_used
        except (OSError, ValueError, TypeError):
            pass
    return installed[0]


def launch_installed_chrome() -> None:
    executable = chrome_executable()
    if executable is None:
        raise RuntimeError("Không tìm thấy Google Chrome cài trên Windows")
    # Chrome without an explicit profile can display the "Who's using Chrome?" picker.
    profile = chrome_extension_profile()
    subprocess.Popen(
        [str(executable), f"--profile-directory={profile}", "--start-minimized", "--no-default-browser-check"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@dataclass
class Job:
    audio: Path | None
    prompt: str
    type: str = "transcribe"
    id: str = field(default_factory=lambda: str(uuid4()))
    finished: threading.Event = field(default_factory=threading.Event)
    reply: str | None = None
    error: str | None = None
    claimed: bool = False


class ChromeBridge:
    def __init__(self, port: int = BRIDGE_PORT) -> None:
        self.port = port
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.closed = threading.Event()
        self.connected = threading.Event()
        self.commands: Queue[Job] = Queue(maxsize=1)
        self.lock = threading.Lock()
        self.extension_id: str | None = None
        self.last_seen = 0.0
        self.current: Job | None = None

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def json_response(self, status: int, data: dict) -> None:
                payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def identify(self) -> bool:
                ext = self.headers.get("X-Pro-Meeting-Extension-Id", "")
                if not EXT_ID.fullmatch(ext):
                    return False
                origin = self.headers.get("Origin", "")
                if origin and origin != f"chrome-extension://{ext}":
                    return False
                with owner.lock:
                    if owner.extension_id not in (None, ext):
                        return False
                    owner.extension_id = ext
                    owner.last_seen = time.monotonic()
                    owner.connected.set()
                return True

            def do_GET(self) -> None:
                if not self.identify():
                    self.json_response(403, {"error": "extension_not_authorized"})
                    return
                url = urlsplit(self.path)
                if url.path == "/poll":
                    try:
                        job = owner.commands.get(timeout=12)
                    except Empty:
                        self.json_response(200, {"command": None})
                        return
                    with owner.lock:
                        if job is not owner.current or job.claimed or owner.closed.is_set():
                            self.json_response(200, {"command": None})
                            return
                        job.claimed = True
                    self.json_response(200, {"command": {
                        "id": job.id, "type": job.type, "prompt": job.prompt,
                        "filename": job.audio.name if job.audio else None,
                    }})
                    return
                if url.path == "/file":
                    params = parse_qs(url.query)
                    request_id = params.get("id", [""])[0]
                    try:
                        offset = int(params.get("offset", ["-1"])[0])
                    except ValueError:
                        offset = -1
                    with owner.lock:
                        job = owner.current
                        allowed = job is not None and job.id == request_id and job.claimed and not job.finished.is_set()
                    if not allowed or offset < 0 or job.audio is None:
                        self.json_response(404, {"error": "unknown_audio"})
                        return
                    path = job.audio.resolve()
                    if CHUNKS_DIR.resolve() not in path.parents or not path.is_file():
                        self.json_response(404, {"error": "audio_unavailable"})
                        return
                    size = path.stat().st_size
                    if not 0 < size <= MAX_AUDIO_BYTES or offset > size:
                        self.json_response(400, {"error": "audio_size_invalid"})
                        return
                    with path.open("rb") as audio_file:
                        audio_file.seek(offset)
                        part = audio_file.read(FILE_PART_BYTES)
                    self.json_response(200, {
                        "id": request_id, "offset": offset, "size": size,
                        "base64": base64.b64encode(part).decode("ascii"),
                        "nextOffset": offset + len(part), "done": offset + len(part) == size,
                    })
                    return
                self.json_response(404, {"error": "not_found"})

            def do_POST(self) -> None:
                if not self.identify():
                    self.json_response(403, {"error": "extension_not_authorized"})
                    return
                if urlsplit(self.path).path != "/result":
                    self.json_response(404, {"error": "not_found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1 or length > MAX_RESULT_BYTES:
                        raise ValueError("invalid_result_size")
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError):
                    self.json_response(400, {"error": "invalid_result"})
                    return
                with owner.lock:
                    job = owner.current
                    if not job or not job.claimed or body.get("id") != job.id:
                        self.json_response(409, {"error": "unknown_job"})
                        return
                    if not job.finished.is_set():
                        if body.get("ok") is True and isinstance(body.get("text"), str):
                            job.reply = body["text"][:120_000]
                        else:
                            job.error = str(body.get("error", "chatgpt_failed"))[:1000]
                        job.finished.set()
                self.json_response(200, {"ok": True})

        try:
            self.server = ThreadingHTTPServer((BRIDGE_HOST, self.port), Handler)
            self.server.daemon_threads = True
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="chrome-bridge")
            self.thread.start()
        except OSError as error:
            raise RuntimeError(f"Không mở được Chrome Bridge trên cổng {self.port}: {error}") from error

    def wait_connected(self, should_stop) -> bool:
        while not self.closed.is_set() and not should_stop():
            if self.connected.wait(0.5):
                with self.lock:
                    if time.monotonic() - self.last_seen < 30:
                        return True
        return False

    def prepare_chat(self) -> str:
        return self._dispatch(Job(audio=None, prompt="", type="prepare"), timeout=160)

    def send_audio(self, audio: Path, prompt: str, timeout: int) -> str:
        if not audio.is_file() or not 0 < audio.stat().st_size <= MAX_AUDIO_BYTES:
            raise RuntimeError("Đoạn WAV không tồn tại hoặc lớn hơn giới hạn 8MB")
        if not self.connected.is_set() or time.monotonic() - self.last_seen > 40:
            raise RuntimeError("Chrome extension đã ngắt kết nối")
        return self._dispatch(Job(audio=audio, prompt=prompt), timeout)

    def _dispatch(self, job: Job, timeout: int) -> str:
        with self.lock:
            if self.current is not None:
                raise RuntimeError("Đã có đoạn âm thanh đang xử lý")
            self.current = job
        try:
            self.commands.put_nowait(job)
            if not job.finished.wait(timeout):
                raise TimeoutError("ChatGPT không phản hồi kịp; sẽ không gửi lại đoạn chưa rõ trạng thái")
            if job.error:
                raise RuntimeError(job.error)
            if not job.reply or not job.reply.strip():
                raise RuntimeError("ChatGPT không trả về nội dung phiên âm")
            return job.reply.strip()
        finally:
            with self.lock:
                if self.current is job:
                    self.current = None
            try:
                self.commands.get_nowait()  # Only a not-yet-claimed command remains queued.
            except Empty:
                pass

    def close(self) -> None:
        self.closed.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
