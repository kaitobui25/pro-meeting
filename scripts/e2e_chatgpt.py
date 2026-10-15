"""Check a real audio upload in the signed-in Chrome with Pro Meeting extension."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meeting.chatgpt_web import ChatGPTWeb
from meeting.config import CHUNKS_DIR


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path, help="WAV clip containing known speech")
    args = parser.parse_args()
    source = args.audio.resolve(strict=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    destination = CHUNKS_DIR / "segment-91001.wav"
    if source != destination:
        shutil.copyfile(source, destination)
    try:
        with ChatGPTWeb(print) as chat:
            chat.await_login(lambda: False)
            answer = chat.transcribe_translate(destination, 91001)
            print("MODEL_REPLY_START")
            print(answer)
            print("MODEL_REPLY_END")
            if "NGUYÊN VĂN" not in answer or "BẢN DỊCH TIẾNG VIỆT" not in answer:
                print("FAILED: Invalid transcript/translation response")
                return 1
            print("PASSED: Chrome extension upload, send receipt and ChatGPT response")
            return 0
    finally:
        if source != destination:
            destination.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
