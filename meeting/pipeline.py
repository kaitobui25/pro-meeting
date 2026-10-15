"""Coordinate independent capture and sequential local or web requests."""

from __future__ import annotations

from pathlib import Path
from queue import Empty, Full, Queue
import threading
from typing import Callable

from .capture import AudioChunk, MeetingCapture
from .chatgpt_web import ChatGPTWeb
from .config import CHUNKS_DIR, MAX_PENDING_CHUNKS

UiCallback = Callable[[str, str], None]


class MeetingPipeline:
    def __init__(self, emit: UiCallback) -> None:
        self.emit = emit
        self.capture_stop = threading.Event()
        self.shutdown = threading.Event()
        self.pending: Queue[AudioChunk] = Queue(maxsize=MAX_PENDING_CHUNKS)
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
        self.threads = [
            threading.Thread(target=self._translate_loop, name="processing-worker", daemon=True),
        ]
        self.threads[0].start()

    def stop_recording(self) -> None:
        self.capture_stop.set()
        self.emit("status", "Đã dừng thu âm. Đang xử lý các đoạn đã ghi...")

    def close(self) -> None:
        self.capture_stop.set()
        self.shutdown.set()
        while True:
            try:
                self.pending.get_nowait().path.unlink(missing_ok=True)
                self.pending.task_done()
            except Empty:
                break

    def _fail(self, message: str) -> None:
        self.emit("error", message)
        self.capture_stop.set()
        self.shutdown.set()
        while True:
            try:
                self.pending.get_nowait().path.unlink(missing_ok=True)
                self.pending.task_done()
            except Empty:
                break

    def _queue_chunk(self, chunk: AudioChunk) -> None:
        if self.shutdown.is_set():
            chunk.path.unlink(missing_ok=True)
            return
        try:
            self.pending.put_nowait(chunk)
        except Full:
            chunk.path.unlink(missing_ok=True)
            self.emit("warning", "Xử lý âm thanh chậm; hàng đợi đầy. Đã bỏ qua đoạn âm thanh mới")
            return
        self.emit("status", f"Đã thu đoạn {chunk.index} ({chunk.duration_seconds:.0f}s); còn {self.pending.qsize()} đoạn chờ")

    def _translate_loop(self) -> None:
        try:
            with ChatGPTWeb(lambda msg: self.emit("status", msg)) as chat:
                chat.await_login(self.shutdown.is_set)
                if not self.capture_stop.is_set():
                    capture = MeetingCapture(
                        CHUNKS_DIR,
                        self.capture_stop,
                        self._queue_chunk,
                        lambda msg: self.emit("status", msg),
                        lambda msg: self._fail(msg),
                    )
                    worker = threading.Thread(target=capture.run, name="wasapi-capture", daemon=True)
                    self.threads.append(worker)
                    worker.start()
                while not self.shutdown.is_set():
                    try:
                        chunk = self.pending.get(timeout=0.5)
                    except Empty:
                        if self.capture_stop.is_set() and not any(t.name == "wasapi-capture" and t.is_alive() for t in self.threads) and self.pending.empty():
                            self.emit("status", "Đã hoàn thành các đoạn đã ghi")
                            return
                        continue
                    try:
                        self.emit("status", f"Đang xử lý đoạn {chunk.index}")
                        response = chat.transcribe_translate(chunk.path, chunk.index)
                        self.emit("transcript", f"Đoạn {chunk.index} · {chunk.started_at:%H:%M:%S}\n{response}")
                    finally:
                        chunk.path.unlink(missing_ok=True)
                        self.pending.task_done()
        except Exception as error:
            if not self.shutdown.is_set():
                self._fail(f"Pro Meeting: {error}")
