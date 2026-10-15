"""Route meeting audio to local CPU models or signed-in ChatGPT Web."""

from __future__ import annotations

import os

from pathlib import Path
import re
from typing import Callable

from .browser_bridge import ChromeBridge, launch_installed_chrome
from .config import CHAT_TIMEOUT_SECONDS, browser_mode, processing_mode
from .neo_browser import NeoBrowser
from .local_asr import LocalSpeechRecognizer
from .local_translate import LocalJapaneseVietnamese
import time


PROMPT = """Hãy nghe duy nhất file âm thanh tôi vừa đính kèm. Đây là đoạn {index} của cuộc họp.
1. Phiên âm chính xác bằng ngôn ngữ gốc, không tự thêm lời nói.
2. Dịch toàn bộ lời nói sang tiếng Việt, giữ thuật ngữ và tên riêng.
3. Nếu một phần âm thanh không rõ hoặc không nhận diện được, chỉ viết chính xác .... tại chỗ đó ở cả hai mục. Tuyệt đối không viết các câu giải thích như [Không nghe rõ], [Không nhận diện được nội dung.] hay [Phần lớn âm thanh không đủ rõ để phiên âm và dịch chính xác.]. Nếu toàn bộ không nghe rõ, viết .... ở mỗi mục.
Chỉ trả về hai mục theo mẫu:
NGUYÊN VĂN:
<nội dung phiên âm>
BẢN DỊCH TIẾNG VIỆT:
<nội dung dịch>"""

FAST_PROMPT = """Nghe file âm thanh đính kèm. Phiên âm đúng nguyên ngôn ngữ gốc và dịch sát sang tiếng Việt; không tự thêm lời. Phần nào không rõ chỉ viết chính xác ...., không giải thích. Chỉ trả hai mục:
NGUYÊN VĂN:
<phiên âm>
BẢN DỊCH TIẾNG VIỆT:
<bản dịch>"""


_INAUDIBLE = re.compile(
    r"[\[\(]?[\s]*"
    r"(?:Không nghe rõ|Không nhận diện được nội dung|Phần lớn âm thanh không đủ rõ để phiên âm và dịch chính xác)"
    r"\s*[.!。]?\s*[\]\)]?",
    re.IGNORECASE,
)


def clean_transcript(response: str) -> str:
    """Replace diagnostic inaudibility phrases without altering genuine speech."""
    # Cover model variations with enclosing square brackets/curly quotes.
    return _INAUDIBLE.sub("....", response).replace("“....”", "....").replace('"...."', "....")


class ChatGPTWeb:
    def __init__(self, notify: Callable[[str], None]):
        self.notify = notify
        self.browser = browser_mode()
        self.engine = processing_mode(self.browser)
        self.bridge = ChromeBridge() if self.browser == 'chrome' and self.engine == 'web_audio' else None
        self.neo = NeoBrowser() if self.browser == 'neo' and self.engine != 'local_fast' else None
        self.local_asr: LocalSpeechRecognizer | None = None
        self.local_translation: LocalJapaneseVietnamese | None = None
        self.last_timing: dict[str, float | str] = {}

    def __enter__(self) -> ChatGPTWeb:
        if self.bridge is not None:
            self.bridge.start()
        return self

    def __exit__(self, *_args: object) -> None:
        if self.bridge is not None:
            self.bridge.close()

    def await_login(self, should_stop: Callable[[], bool]) -> None:
        """Connect to the existing browser extension; optionally use BrowserOS Neo."""
        browser = self.browser
        if self.engine == 'local_fast':
            self.notify('Đang nạp Whisper Small và NLLB Nhật–Việt để xử lý nhanh tại máy...')
            self.local_asr = LocalSpeechRecognizer()
            self.local_translation = LocalJapaneseVietnamese()
            self.notify('Sẵn sàng: phiên âm + dịch cục bộ, không phải chờ tải WAV lên ChatGPT Web')
            return
        if browser == "neo":
            assert self.neo is not None
            self.notify("Đang mở tab ChatGPT trong BrowserOS Neo đã đăng nhập...")
            self.neo.prepare()
            if self.engine == 'hybrid':
                self.notify('Đang nạp Whisper Small để nhận dạng giọng nói trực tiếp trên máy...')
                self.local_asr = LocalSpeechRecognizer()
                self.notify(f'Đã sẵn sàng: Whisper Small + GPT-6 {self.neo.mode.title()} dịch văn bản')
            else:
                self.notify(f"BrowserOS Neo đã chọn GPT-6 {self.neo.mode.title()} và sẵn sàng nhận WAV")
            return
        elif browser == "chrome":
            assert self.bridge is not None
            self.notify("Đang kết nối Google Chrome đã đăng nhập ChatGPT...")
            launch_installed_chrome()
        else:
            raise ValueError("PRO_MEETING_BROWSER chỉ nhận 'chrome' hoặc 'neo'")
        self.notify("Chờ extension Pro Meeting kết nối qua cổng 8796...")
        if not self.bridge.wait_connected(should_stop):
            raise RuntimeError("Đã dừng trong khi chờ Chrome Extension")
        self.notify(f"Đã kết nối extension: {self.bridge.extension_id}")
        self.notify("Đang chuẩn bị tab ChatGPT trong trình duyệt đã kết nối...")
        ready = self.bridge.prepare_chat()
        mode = ready.partition('mode=')[2].strip() if 'mode=' in ready else 'unverified'
        if mode in ('Instant', 'Medium'):
            self.notify(f"Đã xác minh ChatGPT đang ở chế độ {mode} trong tab Pro Meeting")
        else:
            self.notify("Chưa xác minh được Instant/Medium trong giao diện ChatGPT; sử dụng chế độ đang chọn")
        if should_stop():
            raise RuntimeError("Đã dừng trong khi chuẩn bị Chrome")
        self.notify("Chrome Bridge đã kết nối. Bắt đầu thu âm...")

    def transcribe_translate(self, audio: Path, index: int) -> str:
        if self.engine == 'local_fast':
            self.notify(f'Đang phiên âm và dịch đoạn {index} tại máy...')
        else:
            self.notify(f"Đang gửi đoạn {index} qua ChatGPT Web...")
        if self.engine in ('local_fast', 'hybrid'):
            if self.local_asr is None:
                raise RuntimeError('Chưa khởi tạo mô hình Whisper')
            start = time.monotonic()
            original = self.local_asr.transcribe(audio)
            asr_seconds = time.monotonic() - start
            if self.engine == 'local_fast':
                if self.local_translation is None:
                    raise RuntimeError('Chưa khởi tạo NLLB')
                self.notify(f'Whisper đã phiên âm đoạn {index} trong {asr_seconds:.1f}s; NLLB đang dịch...')
                translation = self.local_translation.translate(original)
            else:
                assert self.neo is not None
                self.notify(f'Whisper đã phiên âm đoạn {index} trong {asr_seconds:.1f}s; ChatGPT Instant đang dịch...')
                translation = ('....' if original == '....' else
                               self.neo.translate_text(original, timeout=CHAT_TIMEOUT_SECONDS + 60))
            response = f'NGUYÊN VĂN:\n{original}\n\nBẢN DỊCH TIẾNG VIỆT:\n{translation}'
            self.last_timing = {
                'mode': self.engine,
                'asr_seconds': round(asr_seconds, 2),
                'translation_seconds': round(time.monotonic() - start - asr_seconds, 2),
                'total_seconds': round(time.monotonic() - start, 2),
            }
        elif self.neo:
            response = self.neo.transcribe_translate(
                audio, FAST_PROMPT, CHAT_TIMEOUT_SECONDS + 60,
            )
            self.last_timing = self.neo.last_timing.copy()
        else:
            assert self.bridge is not None
            response = self.bridge.send_audio(
                audio, PROMPT.format(index=index), timeout=CHAT_TIMEOUT_SECONDS + 60,
            )
        if "NGUYÊN VĂN" not in response or "BẢN DỊCH TIẾNG VIỆT" not in response:
            raise RuntimeError(f"ChatGPT không trả về bản phiên âm và bản dịch cho đoạn {index}: {response[:250]}")
        if self.engine == 'local_fast':
            seconds = self.last_timing['total_seconds']
            exceeded = ' (vượt mục tiêu 30s)' if seconds >= 30 else ''
            self.notify(f'Đã hoàn thành đoạn {index} sau {seconds:.1f}s{exceeded}')
        else:
            self.notify(f"Đã nhận phản hồi ChatGPT cho đoạn {index}")
        return clean_transcript(response)
