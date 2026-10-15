"""Small Windows desktop UI; launch with start.bat."""

import logging
import json
import os
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
import tkinter as tk
from tkinter import scrolledtext

from meeting.config import AUDIO_SOURCE, DATA_DIR, browser_mode, processing_mode
from meeting.pipeline import MeetingPipeline


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(DATA_DIR / "app.log"), level=logging.ERROR)
    root = tk.Tk()
    root.title("Pro Meeting · Live transcript & translation")
    root.geometry("860x600")
    root.minsize(570, 340)

    bar = tk.Frame(root, padx=14, pady=12)
    bar.pack(fill="x")
    tk.Label(bar, text="Pro Meeting", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    source_name = "Micro trong phòng" if AUDIO_SOURCE == "microphone" else "Âm thanh phát từ loa PC"
    backend = processing_mode()
    processing_name = ('Whisper + NLLB tại máy' if backend == 'local_fast'
                       else 'Whisper + ChatGPT Instant' if backend == 'hybrid'
                       else 'ChatGPT Web')
    tk.Label(
        bar, text=f"Thu {source_name.lower()} → {processing_name} → Phiên âm & dịch tiếng Việt",
        font=("Segoe UI", 10),
    ).pack(anchor="w", pady=(2, 8))

    events: Queue[tuple[str, str]] = Queue()
    status = tk.StringVar(value="Đang khởi động...")
    tk.Label(bar, textvariable=status, anchor="w", fg="#235b78", wraplength=820).pack(fill="x")
    output = scrolledtext.ScrolledText(root, font=("Segoe UI", 11), wrap="word", padx=12, pady=12)
    output.pack(fill="both", expand=True, padx=14, pady=(0, 8))
    output.insert("end", "Các đoạn phiên âm và bản dịch sẽ xuất hiện tại đây.\n\n")
    output.configure(state="disabled")

    actions = tk.Frame(root, padx=14, pady=8)
    actions.pack(fill="x")
    pipeline = MeetingPipeline(lambda kind, value: events.put((kind, value)))
    stop_button = tk.Button(actions, text="Dừng thu âm", width=16, command=lambda: (pipeline.stop_recording(), stop_button.configure(state="disabled")))
    stop_button.pack(side="left")
    browser_name = ("Xử lý cục bộ" if backend == 'local_fast' else
                    "BrowserOS Neo" if browser_mode() == 'neo'
                    else "Google Chrome")
    tk.Label(actions, text=f"{browser_name} · Pro Meeting", fg="#666").pack(side="right")

    # Opt-in unattended live smoke test. Never persist meeting speech/transcripts.
    test_seconds = int(os.environ.get("PRO_MEETING_TEST_SECONDS", "0"))
    test_log = os.environ.get("PRO_MEETING_TEST_LOG", "")
    counters = {"chunks": 0, "translated": 0, "silence": 0, "warnings": 0,
                "errors": 0, "audio_discontinuities": 0}
    test_stopped = False

    def metric(kind: str, value: str = "") -> None:
        if not test_log:
            return
        safe_value = ""
        if kind == "status":
            if value.startswith("Đã thu đoạn"):
                counters["chunks"] += 1
                safe_value = "audio_chunk_captured"
            elif value.startswith("Bỏ qua đoạn"):
                counters["silence"] += 1
                safe_value = "silence_skipped"
            elif value.startswith("Đang thu micro"):
                safe_value = "microphone_started"
            elif value.startswith("Đang thu âm từ loa"):
                safe_value = "loopback_started"
            elif value.startswith("Tín hiệu micro nhỏ"):
                safe_value = "microphone_low_gain"
            elif value.startswith("Micro gần như"):
                safe_value = "microphone_no_signal"
            elif value.startswith("Cảnh báo gián đoạn dữ liệu thu micro"):
                counters["audio_discontinuities"] += 1
                safe_value = "microphone_data_discontinuity"
            elif value.startswith("Đang xử lý đoạn"):
                safe_value = "upload_started"
            elif value.startswith("Đã nhận phản hồi"):
                safe_value = "chat_reply_observed"
            elif value.startswith("Đã kết nối extension"):
                safe_value = "extension_connected"
            elif value.startswith("Đã xác minh ChatGPT đang ở chế độ Instant"):
                safe_value = "model_instant_verified"
            elif value.startswith("Đã xác minh ChatGPT đang ở chế độ Medium"):
                safe_value = "model_medium_verified"
            elif value.startswith("Chưa xác minh được Instant/Medium"):
                safe_value = "model_unverified"
            elif value.startswith("Chrome Bridge đã kết nối"):
                safe_value = "chrome_ready"
            elif value.startswith("Đã hoàn thành các đoạn"):
                safe_value = "queue_drained"
            else:
                return
        elif kind == "transcript":
            counters["translated"] += 1
            safe_value = "transcript_received"
        elif kind == "warning":
            counters["warnings"] += 1
            safe_value = "queue_warning"
        elif kind == "error":
            counters["errors"] += 1
            safe_value = "pipeline_error"
            # No speech content or ChatGPT replies in the diagnostics file.
        else:
            return
        record = {"time": datetime.now().isoformat(timespec="seconds"), "event": safe_value,
                  "pending": pipeline.pending.qsize(), "counts": counters.copy()}
        with Path(test_log).open("a", encoding="utf-8") as logfile:
            logfile.write(json.dumps(record, ensure_ascii=False) + "\n")

    def drain_events() -> None:
        try:
            while True:
                kind, value = events.get_nowait()
                metric(kind, value)
                if kind == "status":
                    status.set(value)
                else:
                    if kind == "error":
                        status.set(value)
                        stop_button.configure(state="disabled")
                        logging.error(value)
                    output.configure(state="normal")
                    output.insert("end", f"{value}\n\n" + ("─" * 46) + "\n\n")
                    output.see("end")
                    output.configure(state="disabled")
        except Empty:
            pass
        root.after(200, drain_events)

    def quit_app() -> None:
        pipeline.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", quit_app)
    drain_events()
    root.after(100, pipeline.start)
    if test_seconds:
        metric("status", "test-started")

        def auto_stop():
            nonlocal test_stopped
            test_stopped = True
            pipeline.stop_recording()
            stop_button.configure(state="disabled")
            status.set("Kiểm thử đủ thời lượng. Đang xử lý hàng đợi và chuẩn bị đóng...")
            root.after(180_000, quit_app)  # Hard ceiling on draining unfinished requests.

        def check_drained():
            if test_stopped and not any(worker.is_alive() for worker in pipeline.threads):
                quit_app()
                return
            root.after(1000, check_drained)

        root.after(test_seconds * 1000, auto_stop)
        root.after(1000, check_drained)
    root.mainloop()


if __name__ == "__main__":
    main()
