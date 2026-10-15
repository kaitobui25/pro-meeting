"""Small collection of operational limits for Phase 1."""

import os
from pathlib import Path


def browser_mode() -> str:
    """Neo is the direct-run default; Chrome is an explicit legacy option."""
    value = os.getenv('PRO_MEETING_BROWSER', 'neo').strip().lower()
    if value not in ('neo', 'chrome'):
        raise ValueError('PRO_MEETING_BROWSER chỉ nhận neo hoặc chrome')
    return value


def processing_mode(browser: str | None = None) -> str:
    """Use fast local processing by default unless Chrome was selected."""
    browser = browser or browser_mode()
    selected = os.getenv('PRO_MEETING_ENGINE',
                         'web_audio' if browser == 'chrome' else 'local_fast')
    selected = selected.strip().lower()
    if selected not in ('local_fast', 'hybrid', 'web_audio'):
        raise ValueError('PRO_MEETING_ENGINE chỉ nhận local_fast, hybrid hoặc web_audio')
    if selected == 'hybrid' and browser != 'neo':
        raise ValueError('PRO_MEETING_ENGINE=hybrid cần PRO_MEETING_BROWSER=neo')
    return selected


SAMPLE_RATE = 48_000
CHUNK_SECONDS = 20
MICROPHONE_LONG_CHUNK_SECONDS = 90
UPLOAD_SAMPLE_RATE = 16_000
MIN_LAST_CHUNK_SECONDS = 1
SILENCE_RMS = 0.0015
MAX_PENDING_CHUNKS = 6
# A signed-in ChatGPT web session can spend several minutes in analysis after
# the send receipt. Keep waiting for that exact turn rather than re-uploading.
CHAT_TIMEOUT_SECONDS = int(os.getenv("PRO_MEETING_CHAT_TIMEOUT_SECONDS", "900"))

# In-room meetings: record actual nearby speech, even when the PC is not in the call.
# Set PRO_MEETING_AUDIO_SOURCE=speakers for Zoom/Teams audio coming out of this PC.
AUDIO_SOURCE = os.environ.get("PRO_MEETING_AUDIO_SOURCE", "microphone").lower()

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ProMeeting"
CHUNKS_DIR = DATA_DIR / "chunks"
