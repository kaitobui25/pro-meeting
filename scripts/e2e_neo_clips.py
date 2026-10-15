"""Send existing m4a meeting clips through the real BrowserOS Neo MCP flow.

Usage: set PRO_MEETING_BROWSER=neo, then run this script with a folder path.
No recordings or transcripts are written to disk by this test.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meeting.chatgpt_web import ChatGPTWeb
from meeting.config import CHUNKS_DIR


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--start-index", type=int, default=1,
                        help="One-based index of first clip to test (for resuming)")
    parser.add_argument("--mode", choices=['instant', 'medium'], default='instant')
    parser.add_argument("--audio-seconds", type=float, default=None,
                        help="Trim each source clip to this number of seconds for speed tests")
    parser.add_argument("--loop-source", action="store_true",
                        help="Repeat source audio to test long meeting chunks (combine with --audio-seconds)")
    parser.add_argument("--preview-chars", type=int, default=350,
                        help="Print this many characters of each combined transcription and translation")
    args = parser.parse_args()
    if args.start_index < 1 or args.count < 1:
        parser.error("--start-index and --count must be positive")
    if args.loop_source and not args.audio_seconds:
        parser.error('--loop-source requires --audio-seconds')
    clips = sorted(args.folder.glob("*.m4a"))[args.start_index - 1:args.start_index - 1 + args.count]
    if len(clips) != args.count:
        parser.error(f"Expected {args.count} m4a clips; found {len(clips)}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg is required to convert m4a to WAV")
    os.environ['PRO_MEETING_CHATGPT_MODE'] = args.mode

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Testing {len(clips)} source clips", flush=True)
    with ChatGPTWeb(lambda msg: print(f"STATUS {msg}", flush=True)) as chat:
        chat.await_login(lambda: False)
        for index, source in enumerate(clips, start=args.start_index):
            target = CHUNKS_DIR / f"segment-{91000 + index}.wav"
            started = time.monotonic()
            try:
                subprocess.run(
                    [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                     *(['-stream_loop', '2'] if args.loop_source else []), '-i', str(source),
                     *(['-t', str(args.audio_seconds)] if args.audio_seconds else []),
                     "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)],
                    check=True,
                )
                print(f"CLIP {index} converted WAV={target.stat().st_size} bytes", flush=True)
                reply = chat.transcribe_translate(target, 91000 + index)
                print(f"CLIP {index} PASS seconds={time.monotonic()-started:.1f} chars={len(reply)}", flush=True)
                if chat.last_timing:
                    print(f"TIMING {index} {chat.last_timing}", flush=True)
                print(f"PREVIEW {index}: {reply[:args.preview_chars]}", flush=True)
            except Exception as exc:
                print(f"CLIP {index} FAIL seconds={time.monotonic()-started:.1f} error={exc}", flush=True)
                return 1
            finally:
                target.unlink(missing_ok=True)
    print(f"PASS all {len(clips)} clips", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
