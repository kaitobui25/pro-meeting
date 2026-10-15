"""Measure signed-in GPT-6 text translation alone, without uploading a WAV."""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from meeting.neo_browser import NeoBrowser

os.environ.setdefault('PRO_MEETING_CHATGPT_MODE', 'instant')
browser = NeoBrowser()
start = time.monotonic()
browser.prepare()
print('PREPARE_SECONDS', round(time.monotonic() - start, 2), flush=True)
start = time.monotonic()
answer = browser.translate_text('じゃあ、あれか。一般的なトレーシングはもう先にやっちゃった方がいいですよね。')
print('TRANSLATE_SECONDS', round(time.monotonic() - start, 2), flush=True)
print('TIMINGS', browser.last_timing, flush=True)
print('ANSWER', answer, flush=True)
